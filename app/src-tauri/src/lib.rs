mod backend;

use backend::{Backend, BackendState};
use std::sync::Arc;
use tauri::{Manager, RunEvent, State};

#[tauri::command]
fn backend_status(backend: State<'_, Arc<Backend>>) -> BackendState {
    backend.snapshot()
}

#[tauri::command]
fn restart_backend(backend: State<'_, Arc<Backend>>) {
    backend.restart();
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let backend = Arc::new(Backend::new(app.handle().clone())?);
            app.manage(backend.clone());
            backend.start();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status, restart_backend])
        .build(tauri::generate_context!())
        .expect("error while building the application");

    app.run(|handle, event| {
        // Quitting the app stops the Python backend and its inference worker, which
        // releases the model's memory. ExitRequested covers Cmd+Q and closing the window.
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            if let Some(backend) = handle.try_state::<Arc<Backend>>() {
                backend.stop();
            }
        }
    });
}
