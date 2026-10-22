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
  /** Whisper's timed transcript, once the recording has been transcribed. */
  segments: { start: number; end: number; text: string }[] | null;
  created_at: string;
  updated_at: string;
}

/** How a voice delivers its lines. Expressiveness 0–1, speed 0.8–1.25×, pitch ±2 semitones. */
export interface Style {
  expressiveness: number;
  speed: number;
  pitch: number;
}

/** A candidate reference cut from a recording; the chosen one is what the voice clones. */
export interface Clip {
  id: string;
  voice_id: string;
  reference_id: string;
  start_s: number;
  end_s: number;
  transcript: string;
  quality: Quality;
  score: number;
  demo_generation_id: string | null;
  /** Kept as a named style: survives "Create new takes" and can be picked per generation. */
  name: string;
  kept: boolean;
  created_at: string;
}

export interface Consent {
  confirmed: boolean;
  speaker: string;
  scope: string;
  notes: string;
  recorded_at?: string;
}

/** A voice is cloned from recordings ("clone") or designed from a description ("design"). */
export type VoiceMode = "clone" | "design";

export interface Voice {
  id: string;
  name: string;
  description: string;
  language: string;
  mode: VoiceMode;
  /** How a designed voice should sound; empty for cloned voices. */
  instructions: string;
  status: "draft" | "ready";
  primary_reference_id: string | null;
  preferred_sample_generation_id: string | null;
  clip_id: string | null;
  style: Style;
  consent: Consent;
  created_at: string;
  updated_at: string;
  references: Reference[];
  clips: Clip[];
  /** Versions in other languages, spoken natively from the voice's fingerprint. */
  languages: { language: string; demo_generation_id: string | null; created_at: string }[];
  generation_count: number;
}

export interface Job {
  id: string;
  kind: "tts" | "voice_test" | "segment" | "load_model" | "voice_create";
  status: JobStatus;
  progress: { chunk?: number; chunks?: number; audio_seconds?: number; message?: string; step?: string };
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
  params: { seed?: number; tone?: string | null; fingerprint?: boolean };
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
  state: "not_installed" | "queued" | "starting" | "downloading" | "installed" | "incomplete" | "failed";
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
  tier: "quality" | "lightweight" | "design" | "speech recognition";
  kind: "tts" | "stt";
  /** "clone" checkpoints clone recordings; "design" checkpoints build a voice from text. */
  capability: "clone" | "design";
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
    /** apple: Apple GPU (MLX) · cuda: an NVIDIA GPU · cpu: neither, so generation is slow. */
    accelerator: "apple" | "cuda" | "cpu";
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
