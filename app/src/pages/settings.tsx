import { useQuery, useQueryClient } from "@tanstack/react-query";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { Download, FolderOpen, HardDrive, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { JobProgress } from "@/components/job-progress";
import { PageHeader } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, Switch, Textarea } from "@/components/ui/form";
import { Badge, Callout, Card, Progress, SectionTitle, Tabs } from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { inTauri } from "@/lib/backend";
import { toastError, useJob, useLanguages, useModels, useSettings, useStatus } from "@/lib/hooks";
import type { ModelEntry, Preferences } from "@/lib/types";
import { formatBytes } from "@/lib/utils";

function useSave() {
  const queryClient = useQueryClient();
  return async (body: Partial<Preferences>, message = "Settings saved") => {
    try {
      const next = await api.updateSettings(body);
      queryClient.setQueryData(["settings"], next);
      await queryClient.invalidateQueries({ queryKey: ["languages"] });
      if (message) toast.success(message);
    } catch (err) {
      toastError(err, "Could not save");
    }
  };
}

function ModelRow({ model, isDefault, onDefault }: { model: ModelEntry; isDefault: boolean; onDefault: () => void }) {
  const queryClient = useQueryClient();
  const [loadJob, setLoadJob] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const job = useJob(loadJob, () => {
    setLoadJob(null);
    void queryClient.invalidateQueries({ queryKey: ["models"] });
  });
  const s = model.status;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["models"] });
  const act = (fn: () => Promise<unknown>, label: string) => async () => {
    try {
      await fn();
      await refresh();
    } catch (err) {
      toastError(err, label);
    }
  };
  const percent = s.total_bytes ? ((s.downloaded_bytes ?? 0) / s.total_bytes) * 100 : null;

  return (
    <div className="py-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{model.label}</p>
            <Badge tone={model.tier === "quality" ? "ink" : model.kind === "stt" ? "blue" : "neutral"}>
              {model.kind === "stt" ? "Speech recognition" : model.tier === "quality" ? "Quality" : "Lightweight"}
            </Badge>
            {model.loaded && <Badge tone="green">Loaded</Badge>}
            {isDefault && <Badge tone="blue">Default</Badge>}
          </div>
          <p className="selectable mt-0.5 text-xs text-ink-3">
            {model.repo_id} · ~{model.approx_download_gb} GB download · ~{model.approx_memory_gb} GB memory (estimate)
          </p>
          {model.notes && <p className="mt-1 text-[13px] text-ink-2">{model.notes}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {s.state === "installed" && (
            <>
              {!isDefault && model.kind === "tts" && (
                <Button size="sm" variant="ghost" onClick={onDefault}>
                  Make default
                </Button>
              )}
              {model.kind !== "tts" ? null : model.loaded ? (
                <Button size="sm" variant="outline" onClick={act(() => api.unloadModel(), "Could not unload")}>
                  Unload
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!!loadJob}
                  onClick={async () => {
                    try {
                      setLoadJob((await api.loadModel(model.id)).job_id);
                    } catch (err) {
                      toastError(err, "Could not load");
                    }
                  }}
                >
                  Load
                </Button>
              )}
              <Button size="icon-sm" variant="ghost" onClick={() => setConfirmDelete(true)} aria-label="Delete model files">
                <Trash2 />
              </Button>
            </>
          )}
          {(s.state === "not_installed" || s.state === "failed" || s.state === "incomplete") && (
            <Button size="sm" onClick={act(() => api.downloadModel(model.id), "Download could not start")}>
              <Download /> {s.state === "not_installed" ? "Download" : "Resume download"}
            </Button>
          )}
          {(s.state === "downloading" || s.state === "queued" || s.state === "starting") && (
            <Button size="sm" variant="ghost" onClick={act(() => api.cancelDownload(model.id), "Could not cancel")}>
              <X /> Cancel
            </Button>
          )}
        </div>
      </div>
      {s.state === "queued" && <p className="mt-1 text-xs text-ink-3">Queued: starts when the current download finishes.</p>}
      {s.state === "downloading" && (
        <div className="mt-3">
          <Progress value={percent} />
          <p className="num mt-1 text-xs text-ink-3">
            {formatBytes(s.downloaded_bytes)} of {formatBytes(s.total_bytes)}
          </p>
        </div>
      )}
      {s.state === "installed" && (
        <p className="selectable mt-1 text-xs text-ink-3">
          Installed · {formatBytes(s.size_bytes)} · {s.path}
        </p>
      )}
      {(s.state === "failed" || s.state === "incomplete") && (
        <Callout tone="amber" className="mt-3">
          {s.error ?? `The folder is incomplete: ${(s.problems ?? []).join("; ")}.`}
        </Callout>
      )}
      {job && <JobProgress job={job} className="mt-3" />}
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete ${model.label}?`}
        description={`Frees ${formatBytes(s.size_bytes)}. You can download it again later.`}
        onConfirm={() => {
          setConfirmDelete(false);
          void act(() => api.deleteModel(model.id), "Could not delete")();
        }}
      />
    </div>
  );
}

function ModelsTab() {
  const { data: models } = useModels();
  const { data: settings } = useSettings();
  const { data: status } = useStatus();
  const save = useSave();
  return (
    <div className="space-y-5">
      <Card className="px-5">
        <div className="divide-y divide-rule">
          {models?.map((m) => (
            <ModelRow key={m.id} model={m} isDefault={settings?.default_model_id === m.id} onDefault={() => save({ default_model_id: m.id }, "Default model changed")} />
          ))}
        </div>
      </Card>
      <Callout>
        Downloads come from Hugging Face and can resume if interrupted. You can also download a checkpoint yourself, e.g.{" "}
        <code className="selectable rounded bg-panel px-1 text-[12px]">hf download mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16 --local-dir "…/models/qwen3-tts-1.7b-base-bf16"</code>
        ; the app detects it on the next refresh. Only one model is held in memory at a time.
      </Callout>
      {status && !status.engine.runtime_available && (
        <Callout tone="amber">The MLX runtime is not installed in this environment, so models cannot be loaded here.</Callout>
      )}
    </div>
  );
}

function LanguagesTab() {
  const { data: languages } = useLanguages();
  const { data: settings } = useSettings();
  const save = useSave();
  const [notes, setNotes] = useState<Record<string, { status?: string; notes?: string }>>({});
  useEffect(() => {
    if (settings) setNotes(settings.language_notes ?? {});
  }, [settings]);
  if (!languages || !settings) return null;
  const toggle = (code: string, on: boolean) => {
    const next = on ? [...settings.enabled_languages, code] : settings.enabled_languages.filter((c) => c !== code);
    void save({ enabled_languages: next }, "");
  };
  return (
    <div className="space-y-4">
      <Callout>
        Qwen3-TTS supports ten languages, but voice identity and pronunciation have to be checked language by language with
        your own voices. Enable a language once you have listened to it, and note what you found.
      </Callout>
      <Card className="divide-y divide-rule px-5">
        {languages.map((lang) => {
          const entry = notes[lang.code] ?? {};
          return (
            <div key={lang.code} className="flex flex-wrap items-start gap-4 py-3.5">
              <Switch checked={lang.enabled} onCheckedChange={(on) => toggle(lang.code, on)} className="mt-1" />
              <div className="w-32">
                <p className="font-medium">{lang.label}</p>
                {lang.supported_by_loaded_model === false && <p className="text-xs text-red">Not in loaded model</p>}
              </div>
              <div className="w-40">
                <Select
                  size="sm"
                  value={entry.status ?? "untested"}
                  onValueChange={(status) => setNotes({ ...notes, [lang.code]: { ...entry, status } })}
                  options={[
                    { value: "untested", label: "Not evaluated" },
                    { value: "verified", label: "Verified" },
                    { value: "issues", label: "Has issues" },
                  ]}
                />
              </div>
              <Input
                className="h-8 min-w-48 flex-1 text-[13px]"
                placeholder="Evaluation notes: identity, pronunciation, artefacts…"
                value={entry.notes ?? ""}
                onChange={(e) => setNotes({ ...notes, [lang.code]: { ...entry, notes: e.target.value } })}
              />
            </div>
          );
        })}
      </Card>
      <div className="flex justify-end">
        <Button onClick={() => save({ language_notes: notes }, "Evaluation saved")}>Save evaluation</Button>
      </div>
    </div>
  );
}

function AudioTab() {
  const { data: settings } = useSettings();
  const save = useSave();
  const [form, setForm] = useState<Preferences | null>(null);
  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);
  if (!form) return null;
  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) => setForm({ ...form, [key]: value });

  async function chooseFolder() {
    if (!inTauri) return;
    const dir = await openDialog({ directory: true, defaultPath: form!.output_dir, title: "Choose the export folder" });
    if (typeof dir === "string") set("output_dir", dir);
  }

  return (
    <div className="space-y-5">
      <Card className="space-y-4 p-5">
        <SectionTitle>Exports</SectionTitle>
        <Field label="Output folder" hint="Exports from Generate, History, Projects and voice backups are written here.">
          <div className="flex gap-2">
            <Input value={form.output_dir} onChange={(e) => set("output_dir", e.target.value)} />
            {inTauri && (
              <Button variant="outline" onClick={chooseFolder}>
                Choose…
              </Button>
            )}
            <Button variant="ghost" size="icon" onClick={() => api.reveal(form.output_dir).catch((e) => toastError(e))} aria-label="Show in Finder">
              <FolderOpen />
            </Button>
          </div>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Default project export format">
            <Select
              value={form.default_export_format}
              onValueChange={(v) => set("default_export_format", v as "wav" | "mp3")}
              options={[
                { value: "wav", label: "WAV (lossless)" },
                { value: "mp3", label: "MP3" },
              ]}
            />
          </Field>
          <Field label="Default MP3 bitrate">
            <Select
              value={String(form.default_mp3_bitrate)}
              onValueChange={(v) => set("default_mp3_bitrate", Number(v) as 192 | 320)}
              options={[
                { value: "320", label: "320 kbps" },
                { value: "192", label: "192 kbps" },
              ]}
            />
          </Field>
        </div>
      </Card>
      <Card className="space-y-4 p-5">
        <SectionTitle>Synthesis</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Max characters per pass" hint="Longer text is split at sentence boundaries into passes of this size.">
            <Input type="number" min={80} max={1500} value={form.max_chunk_chars} onChange={(e) => set("max_chunk_chars", Number(e.target.value))} />
          </Field>
          <Field label="Pause between sentences (ms)" hint="Inserted where Generate splits text.">
            <Input type="number" min={0} max={5000} value={form.sentence_pause_ms} onChange={(e) => set("sentence_pause_ms", Number(e.target.value))} />
          </Field>
          <Field label="Pause between paragraphs (ms)">
            <Input type="number" min={0} max={5000} value={form.paragraph_pause_ms} onChange={(e) => set("paragraph_pause_ms", Number(e.target.value))} />
          </Field>
        </div>
      </Card>
      <Card className="space-y-4 p-5">
        <SectionTitle>Memory</SectionTitle>
        <Field label="Unload the model after idle minutes" hint="0 keeps it loaded until you unload it or quit.">
          <Input type="number" min={0} max={1440} value={form.idle_unload_minutes} onChange={(e) => set("idle_unload_minutes", Number(e.target.value))} className="w-32" />
        </Field>
        <label className="flex items-center gap-3 text-[13px]">
          <Switch checked={form.unload_on_memory_pressure} onCheckedChange={(v) => set("unload_on_memory_pressure", v)} />
          Unload the model when macOS reports critical memory pressure
        </label>
      </Card>
      <Card className="space-y-4 p-5">
        <SectionTitle>Appearance</SectionTitle>
        <Select
          className="w-48"
          value={form.theme}
          onValueChange={(v) => set("theme", v as Preferences["theme"])}
          options={[
            { value: "system", label: "Match macOS" },
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      </Card>
      <div className="flex justify-end">
        <Button
          onClick={() =>
            save({
              output_dir: form.output_dir,
              default_export_format: form.default_export_format,
              default_mp3_bitrate: form.default_mp3_bitrate,
              max_chunk_chars: form.max_chunk_chars,
              sentence_pause_ms: form.sentence_pause_ms,
              paragraph_pause_ms: form.paragraph_pause_ms,
              idle_unload_minutes: form.idle_unload_minutes,
              unload_on_memory_pressure: form.unload_on_memory_pressure,
              theme: form.theme,
            })
          }
        >
          Save settings
        </Button>
      </div>
    </div>
  );
}

function StorageTab() {
  const queryClient = useQueryClient();
  const { data: storage, refetch } = useQuery({ queryKey: ["storage"], queryFn: api.storage });
  const { data: status } = useStatus();
  const [source, setSource] = useState("backend");
  const { data: logs, refetch: refetchLogs } = useQuery({ queryKey: ["logs", source], queryFn: () => api.logs(source) });
  const labels: Record<string, string> = {
    models: "Models",
    voices: "Voices and recordings",
    projects: "Project takes",
    generations: "Generated speech",
    cache: "Temporary files",
    logs: "Logs",
    database: "Database",
  };
  return (
    <div className="space-y-5">
      <Card className="p-5">
        <SectionTitle
          action={
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => api.reveal(storage?.data_dir ?? "").catch((e) => toastError(e))}>
                <FolderOpen /> Open data folder
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={async () => {
                  try {
                    await api.clearCache();
                    await refetch();
                    await queryClient.invalidateQueries({ queryKey: ["status"] });
                    toast.success("Temporary files cleared");
                  } catch (err) {
                    toastError(err);
                  }
                }}
              >
                Clear temporary files
              </Button>
            </div>
          }
        >
          <span className="flex items-center gap-2">
            <HardDrive className="size-4" /> Storage
          </span>
        </SectionTitle>
        {storage && (
          <>
            <ul className="divide-y divide-rule text-[13px]">
              {Object.entries(storage.categories).map(([key, bytes]) => (
                <li key={key} className="flex justify-between py-2">
                  <span className="text-ink-2">{labels[key] ?? key}</span>
                  <span className="num font-medium">{formatBytes(bytes)}</span>
                </li>
              ))}
            </ul>
            <p className="selectable mt-3 text-xs text-ink-3">
              {storage.data_dir} · {formatBytes(storage.disk_free_bytes)} free on disk
            </p>
          </>
        )}
      </Card>
      <Card className="p-5">
        <SectionTitle
          action={
            <div className="flex items-center gap-2">
              <Tabs
                value={source}
                onValueChange={setSource}
                tabs={[
                  { value: "backend", label: "App" },
                  { value: "inference", label: "Engine" },
                  { value: "downloads", label: "Downloads" },
                ]}
              />
              <Button size="icon-sm" variant="ghost" onClick={() => refetchLogs()} aria-label="Refresh logs">
                <RefreshCw />
              </Button>
            </div>
          }
        >
          Logs
        </SectionTitle>
        <Textarea readOnly value={logs?.lines.join("\n") ?? ""} className="min-h-64 font-mono text-[11px]" />
      </Card>
      {status && (
        <p className="selectable text-xs text-ink-3">
          Voice Studio {status.version} · Python {status.platform.python} · {status.platform.system} {status.platform.mac_version ?? ""}{" "}
          {status.platform.machine}
          {status.engine.info?.details && ` · ${Object.entries(status.engine.info.details).map(([k, v]) => `${k} ${v}`).join(" · ")}`}
        </p>
      )}
    </div>
  );
}

export function Settings() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "models";
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs
        className="mb-6"
        value={tab}
        onValueChange={(v) => setParams({ tab: v })}
        tabs={[
          { value: "models", label: "Models" },
          { value: "languages", label: "Languages" },
          { value: "audio", label: "Audio & exports" },
          { value: "storage", label: "Storage & logs" },
        ]}
      />
      {tab === "models" && <ModelsTab />}
      {tab === "languages" && <LanguagesTab />}
      {tab === "audio" && <AudioTab />}
      {tab === "storage" && <StorageTab />}
    </>
  );
}
