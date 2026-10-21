import { getConnection } from "./backend";
import type {
  Clip,
  Draft,
  ExportResult,
  Generation,
  Job,
  JobRef,
  Language,
  ModelEntry,
  Preferences,
  Project,
  Reference,
  Storage,
  SystemStatus,
  Voice,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const { url, token } = getConnection();
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(`${url}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "backend_unreachable", "Voice Studio's engine is not responding.");
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    if (type.includes("application/json")) {
      const data = await res.json();
      const err = data.error ?? {};
      throw new ApiError(res.status, err.code ?? "error", err.message ?? res.statusText, err.details);
    }
    throw new ApiError(res.status, "error", res.statusText);
  }
  if (type.includes("application/json")) return res.json() as Promise<T>;
  return res.blob() as Promise<T>;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

/** URL an <audio> element or WaveSurfer can load directly (token in the query string). */
export function mediaUrl(path: string, version?: string | number): string {
  const { url, token } = getConnection();
  const sep = path.includes("?") ? "&" : "?";
  return `${url}${path}${sep}token=${encodeURIComponent(token)}${version ? `&v=${version}` : ""}`;
}

export const api = {
  // voices
  voices: () => get<Voice[]>("/api/voices"),
  voice: (id: string) => get<Voice>(`/api/voices/${id}`),
  createVoice: (body: {
    name: string;
    description: string;
    language: string;
    consent: { confirmed: boolean; speaker: string; scope: string; notes: string };
  }) => post<Voice>("/api/voices", body),
  updateVoice: (id: string, body: Partial<Voice> & { consent?: Voice["consent"] }) =>
    patch<Voice>(`/api/voices/${id}`, body),
  deleteVoice: (id: string, deleteGenerations: boolean) =>
    del<void>(`/api/voices/${id}?delete_generations=${deleteGenerations}`),
  uploadReference: (voiceId: string, file: Blob, filename: string, transcript: string) => {
    const form = new FormData();
    form.append("file", file, filename);
    form.append("transcript", transcript);
    return request<Reference>("POST", `/api/voices/${voiceId}/references`, form);
  },
  updateReference: (
    voiceId: string,
    refId: string,
    body: { transcript?: string; language?: string; trim_start_s?: number; trim_end_s?: number },
  ) => patch<Reference>(`/api/voices/${voiceId}/references/${refId}`, body),
  deleteReference: (voiceId: string, refId: string) =>
    del<void>(`/api/voices/${voiceId}/references/${refId}`),
  referenceAudioUrl: (voiceId: string, refId: string, which: "reference" | "source", version?: string) =>
    mediaUrl(`/api/voices/${voiceId}/references/${refId}/audio?which=${which}`, version),
  testVoice: (voiceId: string, body: { text: string; language?: string; model_id?: string }) =>
    post<JobRef>(`/api/voices/${voiceId}/test`, body),
  buildVoice: (voiceId: string, body: { model_id?: string; language?: string; text?: string }) =>
    post<JobRef>(`/api/voices/${voiceId}/create`, body),
  clipAudioUrl: (voiceId: string, clipId: string) => mediaUrl(`/api/voices/${voiceId}/clips/${clipId}/audio`),
  updateClip: (voiceId: string, clipId: string, transcript: string) =>
    patch<Clip>(`/api/voices/${voiceId}/clips/${clipId}`, { transcript }),
  clipDemo: (voiceId: string, clipId: string, body: { model_id?: string; language?: string }) =>
    post<JobRef>(`/api/voices/${voiceId}/clips/${clipId}/demo`, body),
  chooseClip: (voiceId: string, clipId: string) => post<Voice>(`/api/voices/${voiceId}/clips/${clipId}/choose`),
  exportVoice: (voiceId: string) => post<ExportResult>(`/api/voices/${voiceId}/export`),
  importVoice: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<Voice>("POST", "/api/voices/import", form);
  },

  // generation and jobs
  generate: (body: { text: string; voice_id: string; language: string; model_id?: string; seed?: number }) =>
    post<JobRef>("/api/generate", body),
  job: (id: string) => get<Job>(`/api/jobs/${id}`),
  activeJobs: () => get<Job[]>("/api/jobs?status=active"),
  cancelJob: (id: string, force = false) => post<Job>(`/api/jobs/${id}/cancel?force=${force}`),
  retryJob: (id: string) => post<Job>(`/api/jobs/${id}/retry`),

  generations: (params: { kind?: string; voice_id?: string; q?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
    return get<{ items: Generation[]; total: number }>(`/api/generations?${qs}`);
  },
  generation: (id: string) => get<Generation>(`/api/generations/${id}`),
  generationAudioUrl: (id: string) => mediaUrl(`/api/generations/${id}/audio`),
  exportGeneration: (id: string, body: { format: "wav" | "mp3"; bitrate?: number; sample_rate?: number | null }) =>
    post<ExportResult>(`/api/generations/${id}/export`, body),
  deleteGeneration: (id: string) => del<void>(`/api/generations/${id}`),

  drafts: () => get<Draft[]>("/api/drafts"),
  createDraft: (body: Partial<Draft>) => post<Draft>("/api/drafts", body),
  updateDraft: (id: string, body: Partial<Draft>) => put<Draft>(`/api/drafts/${id}`, body),
  deleteDraft: (id: string) => del<void>(`/api/drafts/${id}`),

  // projects
  projects: () => get<Project[]>("/api/projects"),
  project: (id: string) => get<Project>(`/api/projects/${id}`),
  createProject: (body: {
    name: string;
    script: string;
    voice_id: string | null;
    language: string;
    model_id?: string;
    segmentation: "sentence" | "paragraph";
  }) => post<Project>("/api/projects", body),
  updateProject: (id: string, body: Partial<Project>) => put<Project>(`/api/projects/${id}`, body),
  deleteProject: (id: string) => del<void>(`/api/projects/${id}`),
  resegment: (id: string, script: string, segmentation: "sentence" | "paragraph") =>
    post<Project>(`/api/projects/${id}/script`, { script, segmentation }),
  addSegment: (id: string, body: { text: string; after_segment_id?: string | null }) =>
    post<Project>(`/api/projects/${id}/segments`, body),
  updateSegment: (
    id: string,
    segmentId: string,
    body: { text?: string; pause_after_ms?: number; active_generation_id?: string },
  ) => patch<Project>(`/api/projects/${id}/segments/${segmentId}`, body),
  deleteSegment: (id: string, segmentId: string) => del<Project>(`/api/projects/${id}/segments/${segmentId}`),
  reorder: (id: string, segmentIds: string[]) => post<Project>(`/api/projects/${id}/reorder`, { segment_ids: segmentIds }),
  generateProject: (id: string, body: { segment_ids?: string[]; only_missing?: boolean }) =>
    post<Job[]>(`/api/projects/${id}/generate`, body),
  previewProject: (id: string) => post<Blob>(`/api/projects/${id}/preview`),
  exportProject: (
    id: string,
    body: { format: "wav" | "mp3"; bitrate?: number; sample_rate?: number | null; mode: "combined" | "segments" | "both" },
  ) => post<ExportResult>(`/api/projects/${id}/export`, body),

  // models, settings, system
  models: () => get<ModelEntry[]>("/api/models"),
  downloadModel: (model_id: string) => post<unknown>("/api/models/download", { model_id }),
  cancelDownload: (model_id: string) => post<void>("/api/models/download/cancel", { model_id }),
  loadModel: (model_id: string) => post<JobRef>("/api/models/load", { model_id }),
  unloadModel: (force = false) => post<void>("/api/models/unload", { force }),
  deleteModel: (model_id: string) => del<void>(`/api/models/${model_id}`),

  settings: () => get<Preferences>("/api/settings"),
  updateSettings: (body: Partial<Preferences>) => put<Preferences>("/api/settings", body),
  languages: () => get<Language[]>("/api/languages"),

  status: () => get<SystemStatus>("/api/system/status"),
  storage: () => get<Storage>("/api/system/storage"),
  clearCache: () => post<void>("/api/system/clear-cache"),
  logs: (source: string, lines = 400) =>
    get<{ source: string; lines: string[] }>(`/api/system/logs?source=${source}&lines=${lines}`),
  reveal: (path: string) => post<void>("/api/system/reveal", { path }),
};
