import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { api, ApiError } from "./api";
import { getConnection } from "./backend";
import type { Job } from "./types";

const FINISHED = new Set(["completed", "failed", "cancelled"]);

export function isFinished(job: Job | undefined | null): boolean {
  return !!job && FINISHED.has(job.status);
}

/** Polls a job until it finishes; calls onDone once with the final state. */
export function useJob(jobId: string | null | undefined, onDone?: (job: Job) => void) {
  const queryClient = useQueryClient();
  const reported = useRef<string | null>(null);
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (isFinished(q.state.data) ? false : 500),
  });
  useEffect(() => {
    const job = query.data;
    if (job && isFinished(job) && reported.current !== job.id + job.status) {
      reported.current = job.id + job.status;
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["generations"] });
      onDone?.(job);
    }
  }, [query.data, onDone, queryClient]);
  return query.data;
}

export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 2500 });
}

export function useActiveJobs() {
  return useQuery({ queryKey: ["jobs", "active"], queryFn: api.activeJobs, refetchInterval: 1500 });
}

export function useVoices() {
  return useQuery({ queryKey: ["voices"], queryFn: api.voices });
}

export function useLanguages() {
  return useQuery({ queryKey: ["languages"], queryFn: api.languages });
}

export function useModels(poll = false) {
  return useQuery({
    queryKey: ["models"],
    queryFn: api.models,
    refetchInterval: (q) =>
      poll || q.state.data?.some((m) => m.status.state === "downloading") ? 1500 : false,
  });
}

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: api.settings });
}

/**
 * The voice model a picker should start on: the default if it is installed, otherwise the
 * first installed one (so nothing starts on a model that would fail). Null while loading.
 */
export function usePreferredModelId(): string | null {
  const { data: settings } = useSettings();
  const { data: models } = useModels();
  if (!settings || !models) return null;
  const installed = models.filter((m) => m.kind === "tts" && m.status.state === "installed");
  return (installed.find((m) => m.id === settings.default_model_id) ?? installed[0])?.id ?? settings.default_model_id;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function toastError(err: unknown, title = "Something went wrong") {
  toast.error(title, { description: errorMessage(err) });
}

/** Saves a blob (e.g. a voice archive) through a temporary link. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function useConnectionReady(): boolean {
  try {
    getConnection();
    return true;
  } catch {
    return false;
  }
}
