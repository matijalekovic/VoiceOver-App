import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bookmark,
  CheckCircle2,
  Circle,
  Download,
  FileAudio,
  Mic,
  Pencil,
  Scissors,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";
import { Orb } from "@/components/brand";
import { announceExport } from "@/components/export-menu";
import { JobProgress } from "@/components/job-progress";
import { PlayButton } from "@/components/mini-player";
import { LanguagePicker, ModelPicker } from "@/components/pickers";
import { Recorder } from "@/components/recorder";
import { type Delivery, deliveryFor, VoiceControls } from "@/components/voice-controls";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Badge, Callout, Card, Progress, SectionTitle, Skeleton, Tabs } from "@/components/ui/misc";
import { Waveform } from "@/components/waveform";
import { api } from "@/lib/api";
import { toastError, useJob, useModels, usePreferredModelId } from "@/lib/hooks";
import type { Clip, Reference, Voice } from "@/lib/types";
import { cn, formatBytes, formatDate, formatDuration, languageLabel, SAMPLE_LINES } from "@/lib/utils";
import { DeleteVoiceDialog } from "./voices";

/** All of a voice's recordings together; the backend enforces the same limit. */
const MAX_TOTAL_S = 180;
const AUDIO_ACCEPT = ".wav,.mp3,.m4a,.flac,.aac,.aiff,.aif,.caf,.ogg,.webm,audio/*";

function useVoice(voiceId: string) {
  return useQuery({ queryKey: ["voice", voiceId], queryFn: () => api.voice(voiceId) });
}

function Check({ done, children }: { done: boolean; children: React.ReactNode }) {
  return (
    <li className={cn("flex items-center gap-2 text-[13px]", done ? "text-ink-2" : "text-ink")}>
      {done ? <CheckCircle2 className="size-4 text-green" /> : <Circle className="size-4 text-ink-3" />}
      {children}
    </li>
  );
}

function AddRecordings({ voice, remaining, onAdded }: { voice: Voice; remaining: number; onAdded: () => void }) {
  const [mode, setMode] = useState<"upload" | "record">("upload");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const full = remaining < 1;

  async function send(files: { blob: Blob; name: string }[]) {
    if (!files.length) return;
    setProgress({ done: 0, total: files.length });
    for (const [index, file] of files.entries()) {
      try {
        await api.uploadReference(voice.id, file.blob, file.name, "");
        onAdded();
      } catch (err) {
        toastError(err, `“${file.name}” could not be added`);
      }
      setProgress({ done: index + 1, total: files.length });
    }
    setProgress(null);
  }

  const fromList = (list: FileList | null) =>
    void send(Array.from(list ?? []).map((f) => ({ blob: f, name: f.name })));
  const busy = progress !== null;

  return (
    <div className="space-y-3">
      <Tabs
        value={mode}
        onValueChange={(v) => setMode(v as "upload" | "record")}
        tabs={[
          { value: "upload", label: <span className="flex items-center gap-1.5"><Upload className="size-3.5" /> Upload</span> },
          { value: "record", label: <span className="flex items-center gap-1.5"><Mic className="size-3.5" /> Record</span> },
        ]}
      />
      {mode === "upload" ? (
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!busy && !full) fromList(e.dataTransfer.files);
          }}
          className={cn(
            "flex w-full flex-col items-center gap-2 rounded-2xl border border-dashed px-6 py-9 text-center transition-colors disabled:opacity-60",
            dragging ? "border-ink bg-panel-2" : "border-rule-strong hover:bg-panel-2/60",
          )}
          disabled={busy || full}
        >
          <FileAudio className="size-6 text-ink-3" />
          <span className="font-medium">
            {busy
              ? `Adding ${Math.min(progress.done + 1, progress.total)} of ${progress.total}…`
              : full
                ? "3 minutes reached — remove a recording to add another"
                : "Drop recordings here or click to choose"}
          </span>
          <span className="text-xs text-ink-3">
            WAV, MP3, M4A or FLAC · one or several files · {formatDuration(remaining)} left of 3:00
          </span>
          <input
            ref={input}
            type="file"
            multiple
            accept={AUDIO_ACCEPT}
            className="hidden"
            onChange={(e) => {
              fromList(e.target.files);
              e.target.value = "";
            }}
          />
        </button>
      ) : (
        <Recorder onRecorded={(blob, name) => void send([{ blob, name }])} />
      )}
    </div>
  );
}

function RecordingRow({ voice, reference, onChanged }: { voice: Voice; reference: Reference; onChanged: () => void }) {
  const [trimming, setTrimming] = useState(false);
  const [trim, setTrim] = useState({ start: reference.trim_start_s, end: reference.trim_end_s });
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setTrim({ start: reference.trim_start_s, end: reference.trim_end_s });
  }, [reference.trim_start_s, reference.trim_end_s]);
  const q = reference.quality;
  const errors = q.flags.filter((f) => f.severity === "error");
  const warnings = q.flags.filter((f) => f.severity === "warning");
  const trimChanged =
    Math.abs(trim.start - reference.trim_start_s) > 0.02 || Math.abs(trim.end - reference.trim_end_s) > 0.02;

  async function applyTrim() {
    setSaving(true);
    try {
      await api.updateReference(voice.id, reference.id, { trim_start_s: trim.start, trim_end_s: trim.end });
      setTrimming(false);
      onChanged();
    } catch (err) {
      toastError(err, "Could not trim");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    try {
      await api.deleteReference(voice.id, reference.id);
      onChanged();
    } catch (err) {
      toastError(err, "Could not remove the recording");
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <PlayButton id={reference.id} url={api.referenceAudioUrl(voice.id, reference.id, "reference", reference.updated_at)} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-medium">{reference.original_filename}</p>
          <p className="truncate text-[12.5px] text-ink-3">
            <span className="num">{formatDuration(reference.duration_s)}</span> ·{" "}
            <span className={q.snr_db < 20 ? "text-amber" : undefined}>≈{q.snr_db.toFixed(0)} dB above noise</span>
            {reference.segments ? (
              <> · “{reference.transcript}”</>
            ) : (
              <> · transcribed when you create the voice</>
            )}
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setTrimming((v) => !v)}>
          <Scissors /> {trimming ? "Close" : "Trim"}
        </Button>
        <Button size="icon-sm" variant="ghost" onClick={remove} aria-label="Remove recording">
          <Trash2 />
        </Button>
      </div>
      {[...errors, ...warnings].map((f) => (
        <Callout key={f.code} tone={f.severity === "error" ? "red" : "amber"} icon={<AlertTriangle />} className="mt-2">
          {f.message}
        </Callout>
      ))}
      {trimming && (
        <div className="mt-3 space-y-2">
          <Waveform
            url={api.referenceAudioUrl(voice.id, reference.id, "source")}
            compact
            height={64}
            region={trim}
            onRegionChange={(start, end) => setTrim({ start, end })}
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-ink-3">
              Drag the edges to leave out coughs, music or other voices. Only speech inside the selection is used.
            </p>
            <Button size="sm" disabled={!trimChanged} loading={saving} onClick={applyTrim}>
              Apply trim
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function RecordingsCard({ voice, onChanged }: { voice: Voice; onChanged: () => void }) {
  const total = voice.references.reduce((sum, r) => sum + r.duration_s, 0);
  return (
    <Card className="p-5">
      <SectionTitle
        action={
          <span className="num text-[13px] text-ink-3">
            {formatDuration(total)} of 3:00
          </span>
        }
      >
        Recordings
      </SectionTitle>
      <Progress value={(total / MAX_TOTAL_S) * 100} className="mb-4" />
      {voice.references.length > 0 && (
        <ul className="mb-4 divide-y divide-rule rounded-xl border border-rule">
          {voice.references.map((r) => (
            <RecordingRow key={r.id} voice={voice} reference={r} onChanged={onChanged} />
          ))}
        </ul>
      )}
      <AddRecordings voice={voice} remaining={MAX_TOTAL_S - total} onAdded={onChanged} />
      <p className="mt-3 text-xs text-ink-3">
        Clean speech from one person, no music or other voices. The more you add (up to 3 minutes), the more there is to
        choose the best clip from.
      </p>
    </Card>
  );
}

function SpeechModelNotice() {
  const queryClient = useQueryClient();
  const { data: models } = useModels();
  const stt = models?.find((m) => m.kind === "stt");
  if (!stt || stt.status.state === "installed") return null;
  const s = stt.status;
  if (s.state === "downloading") {
    const percent = s.total_bytes ? ((s.downloaded_bytes ?? 0) / s.total_bytes) * 100 : null;
    return (
      <Callout tone="blue" className="mb-4">
        <p className="mb-2 font-medium">
          Downloading {stt.label} · {formatBytes(s.downloaded_bytes ?? 0)}
          {s.total_bytes ? ` of ${formatBytes(s.total_bytes)}` : ""}
        </p>
        <Progress value={percent} />
      </Callout>
    );
  }
  return (
    <Callout tone="amber" className="mb-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1">
          Creating a voice transcribes your recordings with {stt.label} (~{stt.approx_download_gb} GB, one-time
          download). {s.state === "failed" && s.error}
        </p>
        <Button
          size="sm"
          onClick={() =>
            api
              .downloadModel(stt.id)
              .then(() => queryClient.invalidateQueries({ queryKey: ["models"] }))
              .catch((err) => toastError(err, "Download could not start"))
          }
        >
          <Download /> {s.state === "not_installed" ? "Download" : "Resume download"}
        </Button>
      </div>
    </Callout>
  );
}

function TakeCard({
  voice,
  clip,
  index,
  modelId,
  language,
  onChanged,
}: {
  voice: Voice;
  clip: Clip;
  index: number;
  modelId: string | null;
  language: string;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [transcript, setTranscript] = useState(clip.transcript);
  const [jobId, setJobId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [naming, setNaming] = useState(false);
  const [styleName, setStyleName] = useState(clip.name);
  const job = useJob(jobId, () => onChanged());
  const redoing = !!job && !["completed", "failed", "cancelled"].includes(job.status);
  const chosen = voice.clip_id === clip.id;
  const source = voice.references.find((r) => r.id === clip.reference_id);
  useEffect(() => setTranscript(clip.transcript), [clip.transcript]);

  async function redo() {
    try {
      if (transcript.trim() !== clip.transcript) await api.updateClip(voice.id, clip.id, { transcript: transcript.trim() });
      setEditing(false);
      setJobId((await api.clipDemo(voice.id, clip.id, { model_id: modelId ?? undefined, language })).job_id);
    } catch (err) {
      toastError(err, "Could not redo the demo");
    }
  }

  async function keepAsStyle(kept: boolean) {
    try {
      await api.updateClip(voice.id, clip.id, kept ? { kept, name: styleName.trim() } : { kept });
      setNaming(false);
      onChanged();
      if (kept) toast.success(`Kept “${styleName.trim()}” — pick it under Style in Text to Speech`);
    } catch (err) {
      toastError(err, "Could not keep the style");
    }
  }

  async function choose() {
    setSaving(true);
    try {
      await api.chooseClip(voice.id, clip.id);
      onChanged();
      toast.success(`“${voice.name}” is saved and ready to use`);
    } catch (err) {
      toastError(err, "Could not save the voice");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-2xl border bg-panel p-4 shadow-card",
        chosen ? "border-ink" : "border-rule",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">Take {index + 1}</p>
        <span className="flex gap-1.5">
          {clip.kept && <Badge tone="blue">Style · {clip.name || "Kept"}</Badge>}
          {chosen ? <Badge tone="ink">In use</Badge> : index === 0 ? <Badge>Best match</Badge> : null}
        </span>
      </div>
      {redoing && job ? (
        <JobProgress job={job} />
      ) : clip.demo_generation_id ? (
        <Waveform key={clip.demo_generation_id} url={api.generationAudioUrl(clip.demo_generation_id)} compact height={48} />
      ) : (
        <p className="text-[13px] text-ink-3">No demo yet.</p>
      )}
      {job?.status === "failed" && <JobProgress job={job} onRetry={(j) => setJobId(j.id)} />}
      <div className="flex items-center gap-2 rounded-xl bg-panel-2 px-2.5 py-2">
        <PlayButton id={`clip-${clip.id}`} url={api.clipAudioUrl(voice.id, clip.id)} label="Play the clip" />
        <p className="min-w-0 flex-1 truncate text-[12.5px] text-ink-2">
          Clip <span className="num">{formatDuration(clip.end_s - clip.start_s)}</span> from{" "}
          {source?.original_filename ?? "a recording"} at <span className="num">{formatDuration(clip.start_s)}</span>
        </p>
      </div>
      {editing ? (
        <div className="space-y-2">
          <Textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} className="min-h-20 text-[13.5px]" />
          <p className="text-xs text-ink-3">Fix any misheard words so the text matches the clip exactly.</p>
        </div>
      ) : (
        <p className="line-clamp-3 text-[13px] text-ink-2">“{clip.transcript}”</p>
      )}
      <div className="mt-auto flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button size="sm" onClick={redo} disabled={!transcript.trim()}>
              Save and redo demo
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" onClick={choose} loading={saving} disabled={chosen || redoing || !clip.demo_generation_id}>
              {chosen ? "Saved" : "Use this voice"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)} disabled={redoing}>
              <Pencil /> Fix words
            </Button>
            {!chosen &&
              (clip.kept ? (
                <Button size="sm" variant="ghost" onClick={() => keepAsStyle(false)}>
                  Remove style
                </Button>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setNaming(true)} disabled={!clip.demo_generation_id}>
                  <Bookmark /> Keep as style
                </Button>
              ))}
          </>
        )}
      </div>
      {naming && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={styleName}
            onChange={(e) => setStyleName(e.target.value.slice(0, 60))}
            placeholder="Name it, e.g. Calm or Energetic"
            className="h-9 max-w-xs"
            autoFocus
            onKeyDown={(e) => e.key === "Enter" && styleName.trim() && void keepAsStyle(true)}
          />
          <Button size="sm" onClick={() => keepAsStyle(true)} disabled={!styleName.trim()}>
            Keep
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setNaming(false)}>
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}

function CreateVoiceCard({ voice, onChanged }: { voice: Voice; onChanged: () => void }) {
  const { data: models } = useModels();
  const [language, setLanguage] = useState(voice.language);
  const [modelId, setModelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, () => onChanged());
  const preferredModelId = usePreferredModelId();
  useEffect(() => {
    if (!modelId && preferredModelId) setModelId(preferredModelId);
  }, [modelId, preferredModelId]);
  const running = !!job && !["completed", "failed", "cancelled"].includes(job.status);
  const total = voice.references.reduce((sum, r) => sum + r.duration_s, 0);
  const sttReady = models?.find((m) => m.kind === "stt")?.status.state === "installed";
  const needsTranscription = voice.references.some((r) => !r.segments);
  const usable = voice.references.some((r) => !r.quality.flags.some((f) => f.severity === "error"));
  const chosenModel = models?.find((m) => m.id === modelId);
  const modelReady = chosenModel?.status.state === "installed";
  const canCreate = usable && total >= 3 && !running && modelReady && (sttReady || !needsTranscription);

  async function create() {
    try {
      setJobId((await api.buildVoice(voice.id, { model_id: modelId ?? undefined, language })).job_id);
    } catch (err) {
      toastError(err, "Could not create the voice");
    }
  }

  return (
    <Card className="p-5">
      <SectionTitle>{voice.clips.length ? "Pick the take you like" : "Create the voice"}</SectionTitle>
      <p className="-mt-1 mb-4 text-[13.5px] text-ink-2">
        Voice Studio transcribes your recordings, cuts the three cleanest 10–25 second clips and reads a demo script with
        each. Listen, then keep the one that sounds most like the speaker.
      </p>
      <SpeechModelNotice />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Demo language" className="w-44">
          <LanguagePicker value={language} onChange={setLanguage} size="sm" />
        </Field>
        <Field label="Model" className="w-56">
          <ModelPicker value={modelId} onChange={setModelId} size="sm" />
        </Field>
        <Button className="ml-auto" onClick={create} disabled={!canCreate}>
          <Wand2 /> {voice.clips.length ? "Create new takes" : "Create voice"}
        </Button>
      </div>
      {!voice.references.length && <p className="mt-3 text-xs text-ink-3">Add a recording first.</p>}
      {chosenModel && !modelReady && (
        <p className="mt-3 text-xs text-amber">
          {chosenModel.label} is not installed. Pick an installed model, or download it in Settings → Models.
        </p>
      )}
      {job && <JobProgress job={job} onRetry={(j) => setJobId(j.id)} className="mt-4" />}
      {voice.clips.length > 0 && !running && (
        <div className="mt-5 grid gap-3">
          {voice.clips.map((clip, index) => (
            <TakeCard
              key={clip.id}
              voice={voice}
              clip={clip}
              index={index}
              modelId={modelId}
              language={language}
              onChanged={onChanged}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

function TryPanel({ voice }: { voice: Voice }) {
  const [text, setText] = useState(SAMPLE_LINES[voice.language] ?? SAMPLE_LINES.english);
  const [language, setLanguage] = useState(voice.language);
  const [modelId, setModelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [latest, setLatest] = useState<string | null>(null);
  const [delivery, setDelivery] = useState<Delivery>(() => deliveryFor(voice));
  const preferredModelId = usePreferredModelId();
  useEffect(() => {
    if (!modelId && preferredModelId) setModelId(preferredModelId);
  }, [modelId, preferredModelId]);
  const job = useJob(jobId, (j) => {
    if (j.status === "completed" && j.generation_id) setLatest(j.generation_id);
  });
  const busy = !!job && !["completed", "failed", "cancelled"].includes(job.status);

  async function run() {
    try {
      setLatest(null);
      setJobId(
        (
          await api.testVoice(voice.id, {
            text,
            language,
            model_id: modelId ?? undefined,
            reference_id: delivery.clipId ?? undefined,
            style: delivery.style,
          })
        ).job_id,
      );
    } catch (err) {
      toastError(err, "Could not start the test");
    }
  }

  return (
    <div className="space-y-4">
      <Textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 1000))} className="min-h-20" />
      <VoiceControls voice={voice} value={delivery} onChange={setDelivery} className="max-w-md" />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Language" className="w-40">
          <LanguagePicker value={language} onChange={setLanguage} size="sm" />
        </Field>
        <Field label="Model" className="w-56">
          <ModelPicker value={modelId} onChange={setModelId} size="sm" />
        </Field>
        <Button className="ml-auto" onClick={run} disabled={busy || !text.trim()}>
          <Sparkles /> Generate
        </Button>
      </div>
      {job && <JobProgress job={job} onRetry={(j) => setJobId(j.id)} />}
      {latest && <Waveform url={api.generationAudioUrl(latest)} autoPlay />}
    </div>
  );
}

function DetailsPanel({ voice, onChanged }: { voice: Voice; onChanged: () => void }) {
  const [name, setName] = useState(voice.name);
  const [description, setDescription] = useState(voice.description);
  const [language, setLanguage] = useState(voice.language);
  const [scope, setScope] = useState(voice.consent.scope);
  const [notes, setNotes] = useState(voice.consent.notes);
  const [busy, setBusy] = useState(false);
  const changed =
    name !== voice.name ||
    description !== voice.description ||
    language !== voice.language ||
    scope !== voice.consent.scope ||
    notes !== voice.consent.notes;

  async function save() {
    setBusy(true);
    try {
      const consentChanged = scope !== voice.consent.scope || notes !== voice.consent.notes;
      await api.updateVoice(voice.id, {
        name,
        description,
        language,
        ...(consentChanged ? { consent: { ...voice.consent, scope, notes, confirmed: true } } : {}),
      });
      onChanged();
      toast.success("Saved");
    } catch (err) {
      toastError(err, "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Description">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Main language">
        <LanguagePicker value={language} onChange={setLanguage} />
      </Field>
      <div className="space-y-3 rounded-xl bg-panel-2/60 p-3.5">
        <p className="flex items-center gap-1.5 text-[13px] font-medium">
          <ShieldCheck className="size-4" /> Consent record
        </p>
        <p className="text-[13px] text-ink-2">
          Speaker <strong className="text-ink">{voice.consent.speaker}</strong>
          {voice.consent.recorded_at && <> · recorded {formatDate(voice.consent.recorded_at)}</>}
        </p>
        <Field label="Permitted uses">
          <Input value={scope} onChange={(e) => setScope(e.target.value)} />
        </Field>
        <Field label="Notes">
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="min-h-16" />
        </Field>
      </div>
      <div className="flex justify-end">
        <Button size="sm" disabled={!changed} loading={busy} onClick={save}>
          Save details
        </Button>
      </div>
    </div>
  );
}

export function VoiceDetail() {
  const { voiceId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: voice, isLoading, error } = useVoice(voiceId);
  const [deleting, setDeleting] = useState(false);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["voice", voiceId] });
    void queryClient.invalidateQueries({ queryKey: ["voices"] });
  };

  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !voice) return <Callout tone="red">This voice could not be loaded.</Callout>;

  const total = voice.references.reduce((sum, r) => sum + r.duration_s, 0);

  return (
    <>
      <div className="mb-7 flex flex-wrap items-center gap-4">
        <Orb size={56} voiceId={voice.id} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[30px] font-medium leading-tight tracking-[-0.02em]">{voice.name}</h1>
            {voice.status === "draft" ? <Badge tone="amber">Draft</Badge> : <Badge tone="green">Ready</Badge>}
          </div>
          <p className="text-[13.5px] text-ink-2">
            {languageLabel(voice.language)} · speaker {voice.consent.speaker}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => api.exportVoice(voice.id).then(announceExport).catch((e) => toastError(e, "Export failed"))}
          >
            <Download /> Export
          </Button>
          <Button variant="danger-ghost" size="sm" onClick={() => setDeleting(true)}>
            <Trash2 /> Delete
          </Button>
          {voice.status === "ready" && (
            <Button size="sm" onClick={() => navigate(`/generate?voice=${voice.id}`)}>
              <Sparkles /> Use voice
            </Button>
          )}
        </div>
      </div>

      {voice.status === "draft" && (
        <Card className="mb-5 flex flex-wrap items-center gap-x-8 gap-y-2 px-5 py-3.5">
          <span className="text-[13px] font-semibold">To finish</span>
          <ul className="flex flex-wrap gap-x-6 gap-y-1.5">
            <Check done={total >= 10}>Add recordings (10 s or more)</Check>
            <Check done={voice.clips.length > 0}>Create the voice</Check>
            <Check done={!!voice.clip_id}>Pick the take you like</Check>
          </ul>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
        <div className="min-w-0 space-y-5">
          <RecordingsCard voice={voice} onChanged={refresh} />
          <CreateVoiceCard voice={voice} onChanged={refresh} />
          {voice.status === "ready" && (
            <Card className="p-5">
              <SectionTitle>Try the voice</SectionTitle>
              <TryPanel voice={voice} />
            </Card>
          )}
        </div>

        <Card className="h-fit p-5">
          <SectionTitle>Details</SectionTitle>
          <DetailsPanel key={voice.updated_at} voice={voice} onChanged={refresh} />
        </Card>
      </div>

      {deleting && <DeleteVoiceDialog voice={voice} onClose={() => setDeleting(false)} onDeleted={() => navigate("/voices")} />}
    </>
  );
}
