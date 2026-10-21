import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Download,
  FileAudio,
  Mic,
  Scissors,
  ShieldCheck,
  Sparkles,
  Star,
  Trash2,
  Upload,
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
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Badge, Callout, Card, SectionTitle, Skeleton, Tabs, Tooltip } from "@/components/ui/misc";
import { Waveform } from "@/components/waveform";
import { api } from "@/lib/api";
import { toastError, useJob, useSettings } from "@/lib/hooks";
import type { Reference, Voice } from "@/lib/types";
import { cn, formatDate, formatDuration, languageLabel, SAMPLE_LINES } from "@/lib/utils";
import { DeleteVoiceDialog } from "./voices";

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

function AddReference({ voice, onAdded }: { voice: Voice; onAdded: () => void }) {
  const [mode, setMode] = useState<"upload" | "record">("upload");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function send(blob: Blob, filename: string) {
    setBusy(true);
    try {
      await api.uploadReference(voice.id, blob, filename, "");
      onAdded();
    } catch (err) {
      toastError(err, "The recording could not be used");
    } finally {
      setBusy(false);
    }
  }

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
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const file = e.dataTransfer.files[0];
            if (file) void send(file, file.name);
          }}
          className={cn(
            "flex w-full flex-col items-center gap-2 rounded-2xl border border-dashed px-6 py-10 text-center transition-colors",
            dragging ? "border-ink bg-panel-2" : "border-rule-strong hover:bg-panel-2/60",
          )}
          disabled={busy}
        >
          <FileAudio className="size-6 text-ink-3" />
          <span className="font-medium">{busy ? "Processing…" : "Drop a recording or click to choose"}</span>
          <span className="text-xs text-ink-3">WAV, MP3, M4A or FLAC · 10–30 seconds of clean speech</span>
          <input
            ref={input}
            type="file"
            accept=".wav,.mp3,.m4a,.flac,.aac,.aiff,.aif,audio/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void send(file, file.name);
              e.target.value = "";
            }}
          />
        </button>
      ) : (
        <Recorder onRecorded={(blob, name) => void send(blob, name)} />
      )}
    </div>
  );
}

function QualitySummary({ reference }: { reference: Reference }) {
  const q = reference.quality;
  const flags = q.flags;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Badge>{formatDuration(q.duration_s)} used</Badge>
        <Badge tone={q.snr_db >= 30 ? "green" : q.snr_db >= 20 ? "neutral" : "amber"}>≈{q.snr_db.toFixed(0)} dB above noise</Badge>
        <Badge>peak {q.peak_dbfs.toFixed(1)} dBFS</Badge>
        {flags.length === 0 && <Badge tone="green">No issues found</Badge>}
      </div>
      {flags.map((f) => (
        <Callout key={f.code} tone={f.severity === "error" ? "red" : "amber"} icon={<AlertTriangle />}>
          {f.message}
        </Callout>
      ))}
    </div>
  );
}

function ReferenceEditor({ voice, reference, onChanged }: { voice: Voice; reference: Reference; onChanged: () => void }) {
  const [trim, setTrim] = useState({ start: reference.trim_start_s, end: reference.trim_end_s });
  const [transcript, setTranscript] = useState(reference.transcript);
  const [savingTrim, setSavingTrim] = useState(false);
  const [savingText, setSavingText] = useState(false);

  useEffect(() => {
    setTrim({ start: reference.trim_start_s, end: reference.trim_end_s });
    setTranscript(reference.transcript);
  }, [reference.id, reference.trim_start_s, reference.trim_end_s, reference.transcript]);

  const trimChanged = Math.abs(trim.start - reference.trim_start_s) > 0.02 || Math.abs(trim.end - reference.trim_end_s) > 0.02;
  const textChanged = transcript.trim() !== reference.transcript;

  async function applyTrim() {
    setSavingTrim(true);
    try {
      await api.updateReference(voice.id, reference.id, { trim_start_s: trim.start, trim_end_s: trim.end });
      onChanged();
    } catch (err) {
      toastError(err, "Could not trim");
    } finally {
      setSavingTrim(false);
    }
  }

  async function saveTranscript() {
    setSavingText(true);
    try {
      await api.updateReference(voice.id, reference.id, { transcript: transcript.trim() });
      onChanged();
      toast.success("Transcript saved");
    } catch (err) {
      toastError(err, "Could not save the transcript");
    } finally {
      setSavingText(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[13px] font-medium">
            Original recording <span className="font-normal text-ink-3">· {reference.original_filename}</span>
          </p>
          <span className="num text-xs text-ink-3">
            Selection {trim.start.toFixed(1)}s – {trim.end.toFixed(1)}s ({(trim.end - trim.start).toFixed(1)}s)
          </span>
        </div>
        <Waveform
          url={api.referenceAudioUrl(voice.id, reference.id, "source")}
          compact
          height={64}
          region={trim}
          onRegionChange={(start, end) => setTrim({ start, end })}
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <p className="text-xs text-ink-3">Drag the edges of the highlighted area to keep only the best 10–30 seconds. Silence at the edges was removed automatically.</p>
          <Button size="sm" variant={trimChanged ? "primary" : "outline"} disabled={!trimChanged} loading={savingTrim} onClick={applyTrim}>
            <Scissors /> Apply trim
          </Button>
        </div>
      </div>

      <div>
        <p className="mb-2 text-[13px] font-medium">Cleaned reference (what the model hears)</p>
        <Waveform url={api.referenceAudioUrl(voice.id, reference.id, "reference", reference.updated_at)} compact height={48} />
        <div className="mt-3">
          <QualitySummary reference={reference} />
        </div>
      </div>

      <Field
        label="Exact transcript"
        htmlFor="transcript"
        hint="Type exactly what is said in the cleaned reference, word for word, including repeated words or fillers. A wrong transcript is the most common cause of poor clones."
      >
        <Textarea
          id="transcript"
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Listen to the cleaned reference and type every word…"
          className="min-h-24"
        />
      </Field>
      <div className="flex justify-end">
        <Button size="sm" disabled={!textChanged} loading={savingText} onClick={saveTranscript}>
          Save transcript
        </Button>
      </div>
    </div>
  );
}

function TestPanel({ voice, onChanged }: { voice: Voice; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const { data: settings } = useSettings();
  const [text, setText] = useState(SAMPLE_LINES[voice.language] ?? SAMPLE_LINES.english);
  const [language, setLanguage] = useState(voice.language);
  const [modelId, setModelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [latest, setLatest] = useState<string | null>(null);
  const { data: tests } = useQuery({
    queryKey: ["generations", "voice_test", voice.id],
    queryFn: () => api.generations({ kind: "voice_test", voice_id: voice.id, limit: 20 }),
  });
  useEffect(() => {
    if (!modelId && settings) setModelId(settings.default_model_id);
  }, [modelId, settings]);
  const job = useJob(jobId, (j) => {
    if (j.status === "completed" && j.generation_id) setLatest(j.generation_id);
    void queryClient.invalidateQueries({ queryKey: ["generations", "voice_test", voice.id] });
  });
  const primary = voice.references.find((r) => r.id === voice.primary_reference_id);
  const canTest = !!primary && !!primary.transcript.trim();
  const busy = !!job && !["completed", "failed", "cancelled"].includes(job.status);

  async function run() {
    try {
      setLatest(null);
      setJobId((await api.testVoice(voice.id, { text, language, model_id: modelId ?? undefined })).job_id);
    } catch (err) {
      toastError(err, "Could not start the test");
    }
  }

  async function setPreview(id: string) {
    try {
      await api.updateVoice(voice.id, { preferred_sample_generation_id: id });
      onChanged();
      toast.success("Preview sample updated");
    } catch (err) {
      toastError(err);
    }
  }

  async function remove(id: string) {
    await api.deleteGeneration(id);
    if (latest === id) setLatest(null);
    onChanged();
    await queryClient.invalidateQueries({ queryKey: ["generations", "voice_test", voice.id] });
  }

  return (
    <div className="space-y-4">
      <Textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 1000))} className="min-h-20" />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Language" className="w-40">
          <LanguagePicker value={language} onChange={setLanguage} size="sm" />
        </Field>
        <Field label="Model" className="w-56">
          <ModelPicker value={modelId} onChange={setModelId} size="sm" />
        </Field>
        <Button className="ml-auto" onClick={run} disabled={!canTest || busy || !text.trim()}>
          <Sparkles /> Generate test
        </Button>
      </div>
      {!canTest && <p className="text-xs text-amber">Add a reference recording and its transcript first.</p>}
      {job && <JobProgress job={job} onRetry={(j) => setJobId(j.id)} />}
      {latest && <Waveform url={api.generationAudioUrl(latest)} autoPlay />}
      {tests && tests.items.length > 0 && (
        <ul className="divide-y divide-rule rounded-xl border border-rule">
          {tests.items.map((g) => (
            <li key={g.id} className="flex items-center gap-3 px-3 py-2">
              <PlayButton id={g.id} url={api.generationAudioUrl(g.id)} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px]">{g.text}</p>
                <p className="text-[11.5px] text-ink-3">
                  {languageLabel(g.language)} · {g.model_id} · {formatDate(g.created_at)}
                </p>
              </div>
              {voice.preferred_sample_generation_id === g.id ? (
                <Badge tone="ink">
                  <Star className="size-3" /> Preview
                </Badge>
              ) : (
                <Tooltip content="Use as this voice's preview sample">
                  <Button size="icon-sm" variant="ghost" onClick={() => setPreview(g.id)}>
                    <Star />
                  </Button>
                </Tooltip>
              )}
              <Button size="icon-sm" variant="ghost" onClick={() => remove(g.id)} aria-label="Delete test">
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
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
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["voice", voiceId] });
    void queryClient.invalidateQueries({ queryKey: ["voices"] });
  };

  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !voice) return <Callout tone="red">This voice could not be loaded.</Callout>;

  const primary = voice.references.find((r) => r.id === voice.primary_reference_id) ?? null;
  const others = voice.references.filter((r) => r.id !== primary?.id);
  const hasTranscript = !!primary?.transcript.trim();
  const blocking = primary?.quality.flags.some((f) => f.severity === "error");
  const tested = voice.generation_count > 0;

  async function markReady() {
    setSaving(true);
    try {
      await api.updateVoice(voice!.id, { status: "ready" });
      refresh();
      toast.success(`“${voice!.name}” is ready to use`);
    } catch (err) {
      toastError(err, "The voice is not ready yet");
    } finally {
      setSaving(false);
    }
  }

  async function makePrimary(id: string) {
    try {
      await api.updateVoice(voice!.id, { primary_reference_id: id });
      refresh();
    } catch (err) {
      toastError(err);
    }
  }

  async function removeReference(id: string) {
    try {
      await api.deleteReference(voice!.id, id);
      refresh();
    } catch (err) {
      toastError(err);
    }
  }

  return (
    <>
      <div className="mb-7 flex flex-wrap items-center gap-4">
        <Orb size={56} voiceId={voice.id} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{voice.name}</h1>
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
          {voice.status === "ready" ? (
            <Button size="sm" onClick={() => navigate(`/generate?voice=${voice.id}`)}>
              <Sparkles /> Use voice
            </Button>
          ) : (
            <Button size="sm" onClick={markReady} loading={saving} disabled={!primary || !hasTranscript || blocking}>
              Save voice
            </Button>
          )}
        </div>
      </div>

      {voice.status === "draft" && (
        <Card className="mb-5 flex flex-wrap items-center gap-x-8 gap-y-2 px-5 py-3.5">
          <span className="text-[13px] font-semibold">To finish</span>
          <ul className="flex flex-wrap gap-x-6 gap-y-1.5">
            <Check done={!!primary && !blocking}>Add a usable reference</Check>
            <Check done={hasTranscript}>Enter its exact transcript</Check>
            <Check done={tested}>Generate and listen to a test</Check>
          </ul>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-5">
          <Card className="p-5">
            <SectionTitle
              action={
                primary && (
                  <Button size="sm" variant="ghost" onClick={() => setAdding((v) => !v)}>
                    {adding ? "Close" : "Add another recording"}
                  </Button>
                )
              }
            >
              Reference recording
            </SectionTitle>
            {(!primary || adding) && (
              <div className={primary ? "mb-6" : undefined}>
                <AddReference
                  voice={voice}
                  onAdded={() => {
                    setAdding(false);
                    refresh();
                  }}
                />
              </div>
            )}
            {primary && <ReferenceEditor voice={voice} reference={primary} onChanged={refresh} />}
            {others.length > 0 && (
              <div className="mt-6">
                <p className="mb-2 text-[13px] font-medium">Other recordings</p>
                <ul className="divide-y divide-rule rounded-xl border border-rule">
                  {others.map((r) => (
                    <li key={r.id} className="flex items-center gap-3 px-3 py-2">
                      <PlayButton id={r.id} url={api.referenceAudioUrl(voice.id, r.id, "reference", r.updated_at)} />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px]">{r.original_filename}</p>
                        <p className="truncate text-[11.5px] text-ink-3">
                          {formatDuration(r.duration_s)} · {r.transcript ? `“${r.transcript}”` : "no transcript"}
                        </p>
                      </div>
                      <Button size="sm" variant="outline" onClick={() => makePrimary(r.id)}>
                        Use this one
                      </Button>
                      <Button size="icon-sm" variant="ghost" onClick={() => removeReference(r.id)} aria-label="Delete recording">
                        <Trash2 />
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle>Test the voice</SectionTitle>
            <TestPanel voice={voice} onChanged={refresh} />
          </Card>
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
