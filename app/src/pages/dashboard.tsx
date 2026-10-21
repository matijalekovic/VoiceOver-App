import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, AudioLines, CheckCircle2, Circle, Cpu, FolderKanban, Mic2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Orb } from "@/components/brand";
import { JobProgress } from "@/components/job-progress";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { Button } from "@/components/ui/button";
import { Badge, Card, SectionTitle } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError, useJob, useModels, useSettings, useStatus, useVoices } from "@/lib/hooks";
import { formatBytes, formatDate, formatDuration, languageLabel } from "@/lib/utils";

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function Step({ done, title, children, to, cta }: { done: boolean; title: string; children: React.ReactNode; to: string; cta: string }) {
  return (
    <div className="flex items-start gap-3 py-3">
      {done ? <CheckCircle2 className="mt-0.5 size-5 text-green" /> : <Circle className="mt-0.5 size-5 text-ink-3" />}
      <div className="min-w-0 flex-1">
        <p className={done ? "text-ink-2 line-through decoration-ink-3" : "font-medium"}>{title}</p>
        {!done && <p className="text-[13px] text-ink-2">{children}</p>}
      </div>
      {!done && (
        <Button asChild size="sm" variant="outline">
          <Link to={to}>{cta}</Link>
        </Button>
      )}
    </div>
  );
}

function EnginePanel() {
  const queryClient = useQueryClient();
  const { data: status } = useStatus();
  const { data: models } = useModels();
  const { data: settings } = useSettings();
  const [loadJob, setLoadJob] = useState<string | null>(null);
  const job = useJob(loadJob, (j) => {
    if (j.status === "completed") setLoadJob(null);
    void queryClient.invalidateQueries({ queryKey: ["models"] });
  });
  const engine = status?.engine;
  const loaded = models?.find((m) => m.id === engine?.loaded_model_id);
  const preferred = models?.find((m) => m.id === settings?.default_model_id);
  const memory = status?.memory;
  const pressure = memory?.pressure_level;

  async function load() {
    if (!preferred) return;
    try {
      setLoadJob((await api.loadModel(preferred.id)).job_id);
    } catch (err) {
      toastError(err, "Could not load the model");
    }
  }

  async function unload() {
    try {
      await api.unloadModel();
      await queryClient.invalidateQueries();
    } catch (err) {
      toastError(err, "Could not unload");
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle
        action={
          loaded ? (
            <Button size="sm" variant="outline" onClick={unload}>
              Unload
            </Button>
          ) : (
            <Button size="sm" onClick={load} disabled={!preferred || preferred.status.state !== "installed" || !!loadJob}>
              Load {preferred?.parameters}
            </Button>
          )
        }
      >
        <span className="flex items-center gap-2">
          <Cpu className="size-4" /> Engine
        </span>
      </SectionTitle>
      {job && <JobProgress job={job} className="mb-3" />}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-[13px]">
        <div>
          <dt className="text-ink-3">Model</dt>
          <dd className="font-medium">{loaded ? loaded.label : "Not loaded"}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Engine memory</dt>
          <dd className="num font-medium">{engine?.worker_rss_bytes ? formatBytes(engine.worker_rss_bytes) : "–"}</dd>
        </div>
        <div>
          <dt className="text-ink-3">System memory free</dt>
          <dd className="num font-medium">
            {memory ? `${formatBytes(memory.available_bytes)} of ${formatBytes(memory.total_bytes)}` : "–"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Memory pressure</dt>
          <dd>
            {pressure == null ? (
              <span className="text-ink-3">n/a</span>
            ) : pressure >= 4 ? (
              <Badge tone="red">Critical</Badge>
            ) : pressure >= 2 ? (
              <Badge tone="amber">Warning</Badge>
            ) : (
              <Badge tone="green">Normal</Badge>
            )}
          </dd>
        </div>
      </dl>
      {engine && !engine.runtime_available && (
        <p className="mt-3 text-xs text-amber">The MLX runtime is not available on this machine; generation needs Apple Silicon.</p>
      )}
    </Card>
  );
}

export function Dashboard() {
  const { data: models } = useModels();
  const { data: voices } = useVoices();
  const { data: recent } = useQuery({ queryKey: ["generations", "recent"], queryFn: () => api.generations({ limit: 6 }) });
  const modelReady = !!models?.some((m) => m.status.state === "installed");
  const voiceReady = !!voices?.some((v) => v.status === "ready");
  const generated = (recent?.total ?? 0) > 0;
  const setupDone = modelReady && voiceReady && generated;

  return (
    <>
      <div className="mb-8 flex items-center gap-5">
        <Orb size={64} />
        <PageHeader title={greeting()} description="Clone authorised voices and produce voiceovers, entirely on this Mac." />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-5">
          {!setupDone && (
            <Card className="px-5 py-3">
              <p className="pt-2 text-[15px] font-semibold">Get started</p>
              <div className="divide-y divide-rule">
                <Step done={modelReady} title="Install a voice model" to="/settings?tab=models" cta="Models">
                  Download Qwen3-TTS 1.7B Base (about 4.5 GB) once. After that everything runs offline.
                </Step>
                <Step done={voiceReady} title="Clone your first voice" to="/clone" cta="Clone">
                  Upload or record up to 3 minutes of clean speech from a speaker who has given permission.
                </Step>
                <Step done={generated} title="Generate a voiceover" to="/generate" cta="Generate">
                  Type a script, pick the voice and language, and export WAV or MP3.
                </Step>
              </div>
            </Card>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { to: "/generate", icon: AudioLines, title: "Text to speech", text: "Short pieces, one take" },
              { to: "/clone", icon: Mic2, title: "Clone a voice", text: "From a consented recording" },
              { to: "/projects", icon: FolderKanban, title: "Long-form project", text: "Segments, takes, pauses" },
            ].map(({ to, icon: Icon, title, text }) => (
              <Link key={to} to={to} className="group rounded-2xl border border-rule bg-panel p-4 shadow-card transition-colors hover:bg-panel-2">
                <Icon className="mb-6 size-5" />
                <p className="font-medium">{title}</p>
                <p className="flex items-center justify-between text-[13px] text-ink-2">
                  {text} <ArrowRight className="size-4 opacity-0 transition-opacity group-hover:opacity-100" />
                </p>
              </Link>
            ))}
          </div>

          <Card className="p-5">
            <SectionTitle
              action={
                <Button asChild size="sm" variant="ghost">
                  <Link to="/history">All history</Link>
                </Button>
              }
            >
              Recent generations
            </SectionTitle>
            {recent?.items.length ? (
              <ul className="divide-y divide-rule">
                {recent.items.map((g) => (
                  <li key={g.id} className="flex items-center gap-3 py-2.5">
                    <PlayButton id={g.id} url={api.generationAudioUrl(g.id)} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13.5px]">{g.text}</p>
                      <p className="text-xs text-ink-3">
                        {g.voice_name} · {languageLabel(g.language)} · {formatDate(g.created_at)}
                      </p>
                    </div>
                    <span className="num text-xs text-ink-3">{formatDuration(g.duration_s)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-ink-3">Nothing generated yet.</p>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <EnginePanel />
          <Card className="p-5">
            <SectionTitle
              action={
                <Button asChild size="sm" variant="ghost">
                  <Link to="/voices">All voices</Link>
                </Button>
              }
            >
              Voices
            </SectionTitle>
            {voices?.length ? (
              <ul className="space-y-2">
                {voices.slice(0, 6).map((v) => (
                  <li key={v.id}>
                    <Link to={`/voices/${v.id}`} className="flex items-center gap-3 rounded-xl px-2 py-1.5 hover:bg-panel-2">
                      <Orb size={30} voiceId={v.id} still />
                      <span className="flex-1 truncate text-[13.5px] font-medium">{v.name}</span>
                      {v.status === "draft" ? <Badge tone="amber">Draft</Badge> : <Badge>{languageLabel(v.language)}</Badge>}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-ink-3">No voices yet.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
