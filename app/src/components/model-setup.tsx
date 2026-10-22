import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Download, Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { toastError, useModels, useStatus } from "@/lib/hooks";
import type { ModelEntry } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";
import { BrandMark } from "./brand";
import { Button } from "./ui/button";
import { Callout, Progress } from "./ui/misc";

const PITCH: Record<string, string> = {
  lightweight: "Faster and lighter. A good fit for computers with 8–16 GB of memory, and the better choice without a dedicated GPU.",
  quality: "The most natural, most faithful voices. Needs more memory and a capable GPU to run quickly.",
};

function ChoiceCard({ model, selected, onToggle }: { model: ModelEntry; selected: boolean; onToggle: () => void }) {
  const installed = model.status.state === "installed";
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={installed}
      aria-pressed={selected || installed}
      className={cn(
        "flex w-full items-start gap-3 rounded-2xl border bg-panel p-4 text-left shadow-card transition-colors",
        selected || installed ? "border-ink" : "border-rule hover:border-rule-strong",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border",
          selected || installed ? "border-accent bg-accent text-accent-ink" : "border-rule-strong",
        )}
      >
        {(selected || installed) && <Check className="size-3.5" strokeWidth={3} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="font-medium">
            {model.tier === "quality" ? "Quality" : "Lightweight"} · {model.parameters}
          </span>
          <span className="num text-[13px] text-ink-3">{installed ? "Installed" : `~${model.approx_download_gb} GB`}</span>
        </span>
        <span className="mt-1 block text-[13px] text-ink-2">{PITCH[model.tier]}</span>
      </span>
    </button>
  );
}

function DownloadRow({ model }: { model: ModelEntry }) {
  const s = model.status;
  const percent = s.total_bytes ? ((s.downloaded_bytes ?? 0) / s.total_bytes) * 100 : null;
  return (
    <li className="space-y-1.5 py-3">
      <div className="flex items-center gap-2 text-[14px]">
        {s.state === "installed" ? (
          <CheckCircle2 className="size-4 text-green" />
        ) : s.state === "failed" || s.state === "incomplete" ? (
          <AlertTriangle className="size-4 text-red" />
        ) : (
          <Loader2 className={cn("size-4 text-ink-3", s.state === "downloading" && "animate-spin")} />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{model.label}</span>
        <span className="num text-[13px] text-ink-3">
          {s.state === "installed"
            ? "Ready"
            : s.state === "queued"
              ? "Waiting"
              : s.state === "starting"
                ? "Starting"
              : s.state === "downloading"
                ? `${formatBytes(s.downloaded_bytes ?? 0)}${s.total_bytes ? ` of ${formatBytes(s.total_bytes)}` : ""}`
                : s.state === "failed" || s.state === "incomplete"
                  ? "Stopped"
                  : ""}
        </span>
        {(s.state === "failed" || s.state === "incomplete") && (
          <Button size="sm" variant="outline" onClick={() => api.downloadModel(model.id).catch((e) => toastError(e, "Could not resume"))}>
            <RotateCcw /> Resume
          </Button>
        )}
      </div>
      {s.state === "downloading" && <Progress value={percent} />}
      {s.error && <p className="text-xs text-red">{s.error}</p>}
    </li>
  );
}

/**
 * First launch: choose which voice models to download (one, the other or both). Speech
 * recognition always comes along, since creating a voice needs it.
 */
export function ModelSetup({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const { data: models } = useModels(true);
  const { data: status } = useStatus();
  const accelerator = status?.engine.accelerator;
  const voiceModels = (models ?? []).filter((m) => m.kind === "tts");
  // One choice per tier: on Macs the 8-bit variant stays in Settings for those who want it.
  const choices = (["lightweight", "quality"] as const)
    .map((tier) => voiceModels.find((m) => m.tier === tier && m.quantization === "bf16"))
    .filter((m): m is ModelEntry => !!m);
  const stt = models?.find((m) => m.kind === "stt");
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [started, setStarted] = useState(false);

  // Default: quality where a GPU will run it, lightweight on a CPU-only PC.
  const selected =
    picked ??
    new Set(
      choices.filter((m) => (accelerator === "cpu" ? m.tier === "lightweight" : m.tier === "quality")).map((m) => m.id),
    );
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };
  const toDownload = [
    ...choices.filter((m) => selected.has(m.id)),
    ...(stt ? [stt] : []),
  ].filter((m) => m.status.state !== "installed");
  // The smallest voice model first, so you can start as soon as possible; then speech
  // recognition; then the rest.
  const smallestVoice = toDownload.filter((m) => m.kind === "tts").sort((a, b) => a.approx_download_gb - b.approx_download_gb)[0];
  const rank = (m: ModelEntry) => (m === smallestVoice ? 0 : m.kind === "stt" ? 1 : 2);
  toDownload.sort((a, b) => rank(a) - rank(b) || a.approx_download_gb - b.approx_download_gb);
  const total = toDownload.reduce((sum, m) => sum + m.approx_download_gb, 0);
  const tracked = started ? [...choices.filter((m) => selected.has(m.id)), ...(stt ? [stt] : [])] : [];
  const anyVoiceReady = voiceModels.some((m) => m.status.state === "installed");
  const allDone = tracked.length > 0 && tracked.every((m) => m.status.state === "installed");

  async function start() {
    try {
      for (const model of toDownload) await api.downloadModel(model.id);
      const best = choices.filter((m) => selected.has(m.id)).sort((a, b) => b.approx_download_gb - a.approx_download_gb)[0];
      if (best) await api.updateSettings({ default_model_id: best.id });
      setStarted(true);
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    } catch (err) {
      toastError(err, "The download could not start");
    }
  }

  return (
    <div className="mx-auto max-w-2xl py-6">
      <BrandMark size={36} />
      <h1 className="mt-5 text-[30px] font-medium leading-tight tracking-[-0.02em]">Choose your voice models</h1>
      <p className="mt-2 text-[14.5px] text-ink-2">
        Voice Studio runs entirely on this computer, so it needs its models on disk. Pick one or both; you can add or
        remove them later in Settings → Models.
      </p>

      {accelerator === "cpu" && (
        <Callout tone="amber" icon={<AlertTriangle />} className="mt-5">
          No NVIDIA graphics card was found, so Voice Studio will run on the processor. That works, but generating
          speech takes several times longer than the audio itself. Lightweight is recommended.
        </Callout>
      )}

      {!started ? (
        <>
          <div className="mt-6 space-y-3">
            {choices.map((m) => (
              <ChoiceCard key={m.id} model={m} selected={selected.has(m.id)} onToggle={() => toggle(m.id)} />
            ))}
          </div>
          {stt && (
            <p className="mt-3 text-[13px] text-ink-3">
              Also included: speech recognition (~{stt.approx_download_gb} GB), which transcribes your recordings when you
              create a voice.
            </p>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button size="lg" onClick={start} disabled={!selected.size && !anyVoiceReady}>
              <Download /> {toDownload.length ? `Download ${total.toFixed(1)} GB` : "Continue"}
            </Button>
            <Button variant="ghost" onClick={onDone}>
              Skip for now
            </Button>
          </div>
          <p className="mt-3 text-xs text-ink-3">Downloads come from Hugging Face, resume if interrupted, and run one after another.</p>
        </>
      ) : (
        <>
          <ul className="mt-6 divide-y divide-rule rounded-2xl border border-rule bg-panel px-4 shadow-card">
            {tracked.map((m) => (
              <DownloadRow key={m.id} model={m} />
            ))}
          </ul>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button size="lg" onClick={onDone} disabled={!anyVoiceReady}>
              {allDone ? "Start using Voice Studio" : "Continue while the rest downloads"}
            </Button>
            {!anyVoiceReady && <span className="text-[13px] text-ink-3">Available once a voice model is ready.</span>}
          </div>
        </>
      )}
    </div>
  );
}
