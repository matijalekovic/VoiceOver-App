//! Owns the Python backend: installs its runtime on first launch, starts it on a free
//! loopback port with a per-launch token, reports progress to the UI, and stops it (with
//! its inference worker) when the app quits.
//!
//! Release builds carry the backend source and a `uv` binary. On first launch (and after
//! an app update changes the locked dependencies) `uv sync` builds a private Python
//! environment in Application Support. Debug builds run the repository's backend with
//! `uv run`, so the UI can be developed against live Python code.

use serde::Serialize;
use std::collections::VecDeque;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

const APP_DIR_NAME: &str = "1PAX Voice Studio";
const LOG_LINES: usize = 200;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(180);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(10);

#[derive(Clone, Serialize)]
pub struct BackendState {
    phase: String, // installing | starting | ready | failed | stopped
    message: String,
    detail: Option<String>,
    url: Option<String>,
    token: Option<String>,
    log: Vec<String>,
}

struct Inner {
    phase: String,
    message: String,
    detail: Option<String>,
    url: Option<String>,
    token: Option<String>,
    log: VecDeque<String>,
    child: Option<Child>,
    stopping: bool,
    generation: u64,
}

pub struct Backend {
    app: AppHandle,
    data_dir: PathBuf,
    inner: Mutex<Inner>,
}

impl Backend {
    pub fn new(app: AppHandle) -> Result<Self, Box<dyn std::error::Error>> {
        let data_dir = app.path().data_dir()?.join(APP_DIR_NAME);
        fs::create_dir_all(&data_dir)?;
        Ok(Self {
            app,
            data_dir,
            inner: Mutex::new(Inner {
                phase: "starting".into(),
                message: "Starting the engine…".into(),
                detail: None,
                url: None,
                token: None,
                log: VecDeque::new(),
                child: None,
                stopping: false,
                generation: 0,
            }),
        })
    }

    pub fn snapshot(&self) -> BackendState {
        let inner = self.inner.lock().unwrap();
        BackendState {
            phase: inner.phase.clone(),
            message: inner.message.clone(),
            detail: inner.detail.clone(),
            url: inner.url.clone(),
            token: inner.token.clone(),
            log: inner.log.iter().cloned().collect(),
        }
    }

    fn set_phase(&self, phase: &str, message: &str, detail: Option<String>) {
        {
            let mut inner = self.inner.lock().unwrap();
            inner.phase = phase.into();
            inner.message = message.into();
            inner.detail = detail;
        }
        let _ = self.app.emit("backend://status", self.snapshot());
    }

    fn push_log(&self, line: String) {
        let mut inner = self.inner.lock().unwrap();
        if inner.log.len() >= LOG_LINES {
            inner.log.pop_front();
        }
        inner.log.push_back(line);
    }

    fn fail(&self, message: &str, detail: String) {
        self.set_phase("failed", message, Some(detail));
    }

    pub fn start(self: &Arc<Self>) {
        let generation = {
            let mut inner = self.inner.lock().unwrap();
            inner.stopping = false;
            inner.generation += 1;
            inner.log.clear();
            inner.generation
        };
        let this = Arc::clone(self);
        thread::spawn(move || {
            if let Err(err) = this.launch(generation) {
                this.fail("The engine could not start.", err);
            }
        });
    }

    pub fn restart(self: &Arc<Self>) {
        let this = Arc::clone(self);
        thread::spawn(move || {
            this.stop();
            this.start();
        });
    }

    fn launch(self: &Arc<Self>, generation: u64) -> Result<(), String> {
        let command = if cfg!(debug_assertions) {
            self.dev_command()?
        } else {
            self.release_command()?
        };
        let mut command = command;
        self.set_phase("starting", "Starting the engine…", None);

        let port = free_port()?;
        let token = random_token()?;
        command
            .env("VOICE_STUDIO_PORT", port.to_string())
            .env("VOICE_STUDIO_TOKEN", &token)
            .env("VOICE_STUDIO_PARENT_PID", std::process::id().to_string())
            .env("VOICE_STUDIO_DATA_DIR", &self.data_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONNOUSERSITE", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(unix)]
        {
            // Its own process group, so quitting can signal the server and its inference
            // worker together.
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        let mut child = command
            .spawn()
            .map_err(|e| format!("Could not run the engine: {e}"))?;
        self.pipe_output(child.stdout.take());
        self.pipe_output(child.stderr.take());
        {
            let mut inner = self.inner.lock().unwrap();
            if inner.generation != generation || inner.stopping {
                drop(inner);
                kill_group(&mut child);
                return Ok(());
            }
            inner.child = Some(child);
        }

        let started = Instant::now();
        loop {
            if self.exited(generation)? {
                return Ok(());
            }
            if health_ok(port, &token) {
                break;
            }
            if started.elapsed() > STARTUP_TIMEOUT {
                self.stop();
                return Err("The engine did not answer within three minutes.".into());
            }
            thread::sleep(Duration::from_millis(250));
        }
        {
            let mut inner = self.inner.lock().unwrap();
            inner.url = Some(format!("http://127.0.0.1:{port}"));
            inner.token = Some(token);
        }
        self.set_phase("ready", "Ready", None);
        self.monitor(generation);
        Ok(())
    }

    /// True if this launch was superseded or stopped; Err if the process died on its own.
    fn exited(&self, generation: u64) -> Result<bool, String> {
        let mut inner = self.inner.lock().unwrap();
        if inner.generation != generation || inner.stopping {
            return Ok(true);
        }
        if let Some(child) = inner.child.as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                inner.child = None;
                let tail: Vec<String> = inner.log.iter().rev().take(8).rev().cloned().collect();
                return Err(format!(
                    "The engine exited ({status}).\n{}",
                    tail.join("\n")
                ));
            }
        }
        Ok(false)
    }

    fn monitor(self: &Arc<Self>, generation: u64) {
        let this = Arc::clone(self);
        thread::spawn(move || loop {
            thread::sleep(Duration::from_millis(500));
            match this.exited(generation) {
                Ok(true) => return,
                Ok(false) => continue,
                Err(detail) => {
                    {
                        let mut inner = this.inner.lock().unwrap();
                        inner.url = None;
                        inner.token = None;
                    }
                    this.fail("The engine stopped unexpectedly.", detail);
                    return;
                }
            }
        });
    }

    fn pipe_output<R: Read + Send + 'static>(self: &Arc<Self>, stream: Option<R>) {
        if let Some(stream) = stream {
            let this = Arc::clone(self);
            thread::spawn(move || {
                for line in BufReader::new(stream).lines().map_while(Result::ok) {
                    this.push_log(line);
                }
            });
        }
    }

    pub fn stop(&self) {
        let child = {
            let mut inner = self.inner.lock().unwrap();
            inner.stopping = true;
            inner.url = None;
            inner.token = None;
            inner.child.take()
        };
        if let Some(mut child) = child {
            kill_group(&mut child);
        }
        self.set_phase("stopped", "The engine is stopped.", None);
    }

    // -- how to run the backend ---------------------------------------------------

    fn dev_command(&self) -> Result<Command, String> {
        let project = std::env::var_os("VOICE_STUDIO_BACKEND_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../../backend"));
        let uv = find_uv().ok_or("uv was not found. Install it with `brew install uv`.")?;
        let mut cmd = Command::new(uv);
        cmd.arg("run")
            .arg("--project")
            .arg(&project)
            .args(["python", "-m", "voice_studio"]);
        Ok(cmd)
    }

    fn release_command(self: &Arc<Self>) -> Result<Command, String> {
        let resources = self
            .app
            .path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("backend");
        let runtime = self.data_dir.join("runtime");
        let python = runtime.join("venv").join("bin").join("python");
        let stamp = runtime_stamp(&resources)?;
        let marker = runtime.join("installed.txt");
        let installed = fs::read_to_string(&marker).unwrap_or_default();
        if installed.trim() != stamp || !python.exists() {
            self.install_runtime(&resources, &runtime)?;
            fs::write(&marker, &stamp).map_err(|e| e.to_string())?;
        }
        let mut cmd = Command::new(python);
        cmd.args(["-m", "voice_studio"]);
        Ok(cmd)
    }

    fn install_runtime(self: &Arc<Self>, resources: &Path, runtime: &Path) -> Result<(), String> {
        self.set_phase(
            "installing",
            "Installing the Python runtime and audio libraries…",
            None,
        );
        let uv = bundled_uv().ok_or("The bundled uv tool is missing from the app.")?;
        let source = runtime.join("src");
        let _ = fs::remove_dir_all(&source);
        copy_dir(resources, &source).map_err(|e| format!("Could not copy the backend: {e}"))?;
        let mut child = Command::new(uv)
            .args(["sync", "--frozen", "--no-dev", "--no-editable", "--project"])
            .arg(&source)
            .env("UV_PROJECT_ENVIRONMENT", runtime.join("venv"))
            .env("UV_PYTHON_INSTALL_DIR", runtime.join("python"))
            .env("UV_CACHE_DIR", runtime.join("cache"))
            .env("UV_PYTHON_PREFERENCE", "only-managed")
            .env("UV_NO_CONFIG", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Could not run uv: {e}"))?;
        // uv reports progress on stderr; forward each line to the setup screen.
        self.pipe_output(child.stdout.take());
        if let Some(stderr) = child.stderr.take() {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                self.push_log(line);
                let _ = self.app.emit("backend://status", self.snapshot());
            }
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        if !status.success() {
            return Err(format!(
                "Installing the runtime failed ({status}). Check the internet connection and try again."
            ));
        }
        // The download cache is only needed during installation.
        let _ = fs::remove_dir_all(runtime.join("cache"));
        Ok(())
    }
}

// -- helpers ------------------------------------------------------------------------

fn kill_group(child: &mut Child) {
    let pid = child.id() as i32;
    #[cfg(unix)]
    unsafe {
        libc::kill(-pid, libc::SIGTERM);
    }
    #[cfg(not(unix))]
    let _ = child.kill();
    let deadline = Instant::now() + SHUTDOWN_GRACE;
    while Instant::now() < deadline {
        if let Ok(Some(_)) = child.try_wait() {
            #[cfg(unix)]
            unsafe {
                // Make sure no straggler in the group (the inference worker) survives.
                libc::kill(-pid, libc::SIGKILL);
            }
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }
    #[cfg(unix)]
    unsafe {
        libc::kill(-pid, libc::SIGKILL);
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    Ok(port)
}

fn random_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|e| format!("Could not generate a token: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn health_ok(port: u16, token: &str) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    response.starts_with("HTTP/1.1 200")
}

/// Changes whenever the bundled backend or its locked dependencies change.
fn runtime_stamp(resources: &Path) -> Result<String, String> {
    let mut hash: u64 = 0xcbf29ce484222325; // FNV-1a
    for name in ["pyproject.toml", "uv.lock", ".python-version"] {
        let bytes = fs::read(resources.join(name)).map_err(|e| format!("{name}: {e}"))?;
        for b in bytes {
            hash ^= b as u64;
            hash = hash.wrapping_mul(0x100000001b3);
        }
    }
    Ok(format!("{}-{hash:016x}", env!("CARGO_PKG_VERSION")))
}

fn bundled_uv() -> Option<PathBuf> {
    // Tauri places external binaries next to the main executable (Contents/MacOS).
    let exe = std::env::current_exe().ok()?;
    let candidate = exe.parent()?.join("uv");
    candidate.exists().then_some(candidate)
}

fn find_uv() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).map(|d| d.join("uv")).collect())
        .unwrap_or_default();
    if let Some(home) = std::env::var_os("HOME") {
        candidates.push(PathBuf::from(home).join(".local/bin/uv"));
    }
    candidates.push("/opt/homebrew/bin/uv".into());
    candidates.push("/usr/local/bin/uv".into());
    candidates.into_iter().find(|c| c.exists())
}

fn copy_dir(from: &Path, to: &Path) -> std::io::Result<()> {
    fs::create_dir_all(to)?;
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}
