import { AlertTriangle, RotateCcw, Square, X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";
import type { Job } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DotSphere } from "./dot-sphere";
import { Button } from "./ui/button";
import { Badge, Progress } from "./ui/misc";

const STAGES: Record<string, string> = {
  queued: "Queued",
  loading: "Loading model",
  synthesizing: "Synthesizing",
  processing: "Processing audio",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function stageLabel(job: Job): string {
  if (job.status === "queued" && job.queue_position) return `Queued · ${job.queue_position} ahead`;
  // Multi-step jobs (creating a voice) name the step they are on.
  if (job.progress.message && job.status !== "loading") return job.progress.message;
  if (job.status === "synthesizing" && job.progress.chunks) {
    return `Synthesizing ${Math.min((job.progress.chunk ?? 0) + 1, job.progress.chunks)} of ${job.progress.chunks}`;
  }
  return STAGES[job.status] ?? job.status;
}

/** Real progress only: chunks completed out of chunks planned. Loading has no measurable progress. */
function progressValue(job: Job): number | null {
  if (job.status === "synthesizing" && job.progress.chunks) {
    return ((job.progress.chunk ?? 0) / job.progress.chunks) * 100;
  }
  if (job.status === "processing") return job.progress.step === "transcribing" || job.progress.step === "choosing" ? null : 100;
  return null;
}

export function JobBadge({ job }: { job: Job }) {
  const tone =
    job.status === "completed"
      ? "green"
      : job.status === "failed"
        ? "red"
        : job.status === "cancelled"
          ? "neutral"
          : "blue";
  return <Badge tone={tone}>{stageLabel(job)}</Badge>;
}

export function JobProgress({ job, onRetry, className }: { job: Job; onRetry?: (job: Job) => void; className?: string }) {
  const [busy, setBusy] = useState(false);
  const active = !["completed", "failed", "cancelled"].includes(job.status);

  async function cancel(force: boolean) {
    setBusy(true);
    try {
      await api.cancelJob(job.id, force);
    } catch (err) {
      toastError(err, "Could not cancel");
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    setBusy(true);
    try {
      const fresh = await api.retryJob(job.id);
      onRetry?.(fresh);
    } catch (err) {
      toastError(err, "Could not retry");
    } finally {
      setBusy(false);
    }
  }

  if (job.status === "failed") {
    return (
      <div className={cn("flex items-start gap-3 rounded-xl bg-red-soft px-3.5 py-3 text-[13px] text-red", className)}>
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">Generation failed</p>
          <p className="selectable mt-0.5 opacity-90">{job.error_message}</p>
        </div>
        <Button size="sm" variant="outline" onClick={retry} loading={busy}>
          <RotateCcw /> Retry
        </Button>
      </div>
    );
  }

  if (!active) return null;
  const audio = job.progress.audio_seconds;
  const value = progressValue(job);
  return (
    <div className={cn("flex items-center gap-4 rounded-2xl border border-rule bg-panel-2/60 py-2 pl-2 pr-4", className)}>
      <DotSphere size={120} active={job.status !== "queued"} progress={value == null ? null : value / 100} className="shrink-0" />
      <div className="min-w-0 flex-1">
      <div className="mb-2 flex items-center justify-between gap-3 text-[13px]">
        <span className="flex min-w-0 items-center gap-2 font-medium">
          {stageLabel(job)}
          {job.cancel_requested && <span className="text-ink-3">· stopping after this part</span>}
        </span>
        <span className="flex items-center gap-2">
          {audio ? <span className="num text-xs text-ink-3">{audio.toFixed(1)}s of audio</span> : null}
          {job.status === "queued" ? (
            <Button size="sm" variant="ghost" onClick={() => cancel(false)} loading={busy}>
              <X /> Cancel
            </Button>
          ) : job.cancel_requested ? (
            <Button size="sm" variant="danger-ghost" onClick={() => cancel(true)} loading={busy} title="Ends the engine process immediately; the model reloads next time.">
              <Square /> Stop now
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => cancel(false)} loading={busy}>
              <X /> Cancel
            </Button>
          )}
        </span>
      </div>
      <Progress value={value} />
      </div>
    </div>
  );
}
