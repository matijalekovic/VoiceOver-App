// Mirrors backend/src/voice_studio/schemas.py.

export type JobStatus =
  | "queued"
  | "loading"
  | "synthesizing"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export interface QualityFlag {
  code: string;
  severity: "warning" | "error";
  message: string;
}

export interface Quality {
  duration_s: number;
  peak_dbfs: number;
  speech_level_dbfs: number;
  noise_floor_dbfs: number;
  snr_db: number;
  clipping_ratio: number;
  flags: QualityFlag[];
}

export interface Reference {
  id: string;
  voice_id: string;
  original_filename: string;
  transcript: string;
  language: string;
  duration_s: number;
  source_duration_s: number;
  trim_start_s: number;
  trim_end_s: number;
  quality: Quality;
  source_quality: Quality | null;
  created_at: string;
  updated_at: string;
}

export interface Consent {
  confirmed: boolean;
  speaker: string;
  scope: string;
  notes: string;
  recorded_at?: string;
}

export interface Voice {
  id: string;
  name: string;
  description: string;
  language: string;
  status: "draft" | "ready";
  primary_reference_id: string | null;
  preferred_sample_generation_id: string | null;
  consent: Consent;
  created_at: string;
  updated_at: string;
  references: Reference[];
  generation_count: number;
}

export interface Job {
  id: string;
  kind: "tts" | "voice_test" | "segment" | "load_model";
  status: JobStatus;
  progress: { chunk?: number; chunks?: number; audio_seconds?: number; message?: string };
  payload: Record<string, unknown>;
  result: { generation_id?: string; stats?: GenerationStats; model_id?: string } | null;
  error_code: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  voice_id: string | null;
  project_id: string | null;
  segment_id: string | null;
  generation_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  queue_position: number | null;
}

export interface JobRef {
  job_id: string;
  status: JobStatus;
}

export interface GenerationStats {
  elapsed_s: number;
  audio_seconds: number;
  real_time_factor: number | null;
  chunks: number;
  load_seconds: number;
  memory: { gpu_peak_bytes?: number; rss_peak_bytes?: number };
}

export interface Generation {
  id: string;
  kind: "tts" | "voice_test" | "segment";
  voice_id: string | null;
  voice_name: string;
  reference_id: string | null;
  project_id: string | null;
  segment_id: string | null;
  text: string;
  language: string;
  model_id: string;
  params: { seed?: number };
  duration_s: number;
  sample_rate: number;
  stats: GenerationStats;
  created_at: string;
}

export interface ExportResult {
  paths: string[];
  folder: string;
}

export interface Draft {
  id: string;
  title: string;
  text: string;
  voice_id: string | null;
  language: string | null;
  created_at: string;
  updated_at: string;
}

export interface Take {
  id: string;
  text: string;
  duration_s: number;
  created_at: string;
  model_id: string;
  voice_name: string;
}

export interface Segment {
  id: string;
  project_id: string;
  position: number;
  text: string;
  pause_after_ms: number;
  active_generation_id: string | null;
  active_take_stale: boolean;
  takes: Take[];
  job: Job | null;
}

export interface Project {
  id: string;
  name: string;
  script: string;
  voice_id: string | null;
  language: string;
  model_id: string;
  default_pause_ms: number;
  paragraph_pause_ms: number;
  created_at: string;
  updated_at: string;
  segments: Segment[];
  segment_count: number;
  generated_count: number;
  duration_s: number;
}

export interface ModelStatus {
  state: "not_installed" | "downloading" | "installed" | "incomplete" | "failed";
  path: string;
  size_bytes?: number;
  downloaded_bytes?: number;
  total_bytes?: number | null;
  error?: string | null;
  problems?: string[];
  source?: string;
}

export interface ModelEntry {
  id: string;
  label: string;
  repo_id: string;
  tier: "quality" | "lightweight";
  parameters: string;
  quantization: string;
  approx_download_gb: number;
  approx_memory_gb: number;
  notes: string;
  status: ModelStatus;
  loaded: boolean;
}

export interface Language {
  code: string;
  label: string;
  enabled: boolean;
  supported_by_loaded_model: boolean | null;
  evaluation: { status?: string; notes?: string };
}

export interface Preferences {
  default_model_id: string;
  output_dir: string;
  idle_unload_minutes: number;
  unload_on_memory_pressure: boolean;
  enabled_languages: string[];
  language_notes: Record<string, { status?: string; notes?: string }>;
  max_chunk_chars: number;
  sentence_pause_ms: number;
  paragraph_pause_ms: number;
  default_export_format: "wav" | "mp3";
  default_mp3_bitrate: 192 | 320;
  theme: "system" | "light" | "dark";
}

export interface SystemStatus {
  version: string;
  engine: {
    state: "stopped" | "loading" | "ready" | "busy";
    loaded_model_id: string | null;
    load_seconds: number | null;
    info: { engine: string; languages: string[]; details: Record<string, string> } | null;
    worker_pid: number | null;
    worker_rss_bytes: number | null;
    last_memory: { gpu_peak_bytes?: number; gpu_active_bytes?: number; rss_peak_bytes?: number };
    runtime_available: boolean;
  };
  memory: { total_bytes: number; available_bytes: number; pressure_level: number | null };
  jobs: { current_job_id: string | null; queued: number };
  platform: { system: string; machine: string; mac_version: string | null; python: string };
  data_dir: string;
}

export interface Storage {
  data_dir: string;
  categories: Record<string, number>;
  disk_free_bytes: number;
  disk_total_bytes: number;
}
