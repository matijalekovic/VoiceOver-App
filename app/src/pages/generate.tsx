import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, RotateCcw, Save, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { toast } from "sonner";
import { ExportMenu } from "@/components/export-menu";
import { JobProgress } from "@/components/job-progress";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { LanguagePicker, ModelPicker, VoicePicker } from "@/components/pickers";
import { type Delivery, deliveryFor, VoiceControls } from "@/components/voice-controls";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/form";
import {
  Callout,
  Card,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
  SectionTitle,
} from "@/components/ui/misc";
import { Waveform } from "@/components/waveform";
import { api } from "@/lib/api";
import { toastError, useJob, useModels, usePreferredModelId, useVoices } from "@/lib/hooks";
import type { Draft, Generation } from "@/lib/types";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

const LIMIT = 20_000;

export function Generate() {
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const location = useLocation();
  const reuse = (location.state as { text?: string; voice_id?: string; language?: string } | null) ?? null;
  const { data: voices } = useVoices();
  const { data: models } = useModels();
  const [text, setText] = useState(reuse?.text ?? "");
  const [voiceId, setVoiceId] = useState<string | null>(reuse?.voice_id ?? params.get("voice"));
  const [language, setLanguage] = useState<string | null>(reuse?.language ?? null);
  const [modelId, setModelId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<Generation | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [delivery, setDelivery] = useState<Delivery>(deliveryFor(null));

  const { data: drafts } = useQuery({ queryKey: ["drafts"], queryFn: api.drafts });
  const { data: recent } = useQuery({
    queryKey: ["generations", "tts"],
    queryFn: () => api.generations({ kind: "tts", limit: 8 }),
  });

  const readyVoices = useMemo(() => (voices ?? []).filter((v) => v.status === "ready"), [voices]);
  const voice = readyVoices.find((v) => v.id === voiceId);

  useEffect(() => {
    if (!voiceId && readyVoices.length) setVoiceId(readyVoices[0].id);
  }, [voiceId, readyVoices]);
  useEffect(() => {
    if (voice && !language) setLanguage(voice.language);
  }, [voice, language]);
  // Each voice starts from its own saved delivery; refetches of the same voice keep edits.
  const deliveryVoiceId = useRef<string | null>(null);
  useEffect(() => {
    if (voice && deliveryVoiceId.current !== voice.id) {
      deliveryVoiceId.current = voice.id;
      setDelivery(deliveryFor(voice));
    }
  }, [voice]);
  const preferredModelId = usePreferredModelId();
  useEffect(() => {
    if (!modelId && preferredModelId) setModelId(preferredModelId);
  }, [modelId, preferredModelId]);

  const job = useJob(jobId, async (finished) => {
    if (finished.status === "completed" && finished.generation_id) {
      setResult(await api.generation(finished.generation_id));
    }
  });
  const busy = !!job && !["completed", "failed", "cancelled"].includes(job.status);
  const modelInstalled = models?.find((m) => m.id === modelId)?.status.state === "installed";

  async function generate() {
    if (!voiceId || !language || !text.trim()) return;
    setSubmitting(true);
    setResult(null);
    try {
      const ref = await api.generate({
        text,
        voice_id: voiceId,
        language,
        model_id: modelId ?? undefined,
        clip_id: delivery.clipId ?? undefined,
        style: delivery.style,
      });
      setJobId(ref.job_id);
    } catch (err) {
      toastError(err, "Could not start generation");
    } finally {
      setSubmitting(false);
    }
  }

  async function saveDraft() {
    const title = text.trim().split(/\s+/).slice(0, 6).join(" ") || "Untitled draft";
    const body = { title, text, voice_id: voiceId, language };
    try {
      const saved = draft ? await api.updateDraft(draft.id, body) : await api.createDraft(body);
      setDraft(saved);
      await queryClient.invalidateQueries({ queryKey: ["drafts"] });
      toast.success("Draft saved");
    } catch (err) {
      toastError(err, "Could not save the draft");
    }
  }

  function openDraft(d: Draft) {
    setDraft(d);
    setText(d.text);
    if (d.voice_id) setVoiceId(d.voice_id);
    if (d.language) setLanguage(d.language);
  }

  async function removeDraft(d: Draft) {
    await api.deleteDraft(d.id);
    if (draft?.id === d.id) setDraft(null);
    await queryClient.invalidateQueries({ queryKey: ["drafts"] });
  }

  return (
    <>
      <PageHeader
        title="Text to Speech"
        description="Turn text into speech with one of your cloned voices."
        actions={
          <DropdownMenu>
            <DropdownTrigger asChild>
              <Button variant="outline" size="sm">
                <FileText /> {draft ? draft.title : "Drafts"}
              </Button>
            </DropdownTrigger>
            <DropdownContent>
              <DropdownItem onSelect={saveDraft} disabled={!text.trim()}>
                <Save /> {draft ? "Save draft" : "Save as draft"}
              </DropdownItem>
              <DropdownItem
                onSelect={() => {
                  setDraft(null);
                  setText("");
                }}
              >
                <Plus /> New
              </DropdownItem>
              {drafts && drafts.length > 0 && (
                <>
                  <DropdownSeparator />
                  <DropdownLabel>Saved drafts</DropdownLabel>
                  {drafts.slice(0, 12).map((d) => (
                    <DropdownItem key={d.id} onSelect={() => openDraft(d)}>
                      <span className="flex-1 truncate">{d.title}</span>
                      <span className="text-xs text-ink-3">{formatDate(d.updated_at)}</span>
                      <span
                        role="button"
                        tabIndex={-1}
                        className="ml-1 rounded p-0.5 text-ink-3 hover:text-red"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          void removeDraft(d);
                        }}
                      >
                        <Trash2 className="size-3.5" />
                      </span>
                    </DropdownItem>
                  ))}
                </>
              )}
            </DropdownContent>
          </DropdownMenu>
        }
      />

      {readyVoices.length === 0 && voices && (
        <Callout tone="amber" className="mb-5">
          You have no ready voices yet. <Link to="/voices/new" className="font-medium underline">Clone a voice</Link> first.
        </Callout>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          <Card className="p-0">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, LIMIT))}
              placeholder="Type or paste the text to speak…"
              className="min-h-[320px] resize-none rounded-2xl border-0 bg-transparent px-5 py-4 text-[15px] focus:border-0"
            />
            <div className="flex items-center justify-between border-t border-rule px-5 py-2.5 text-xs text-ink-3">
              <span className="num">
                {text.length.toLocaleString()} / {LIMIT.toLocaleString()} characters
                {text.length > 3000 && " · consider a project for long scripts"}
              </span>
              {text && (
                <button className="hover:text-ink" onClick={() => setText("")}>
                  Clear
                </button>
              )}
            </div>
          </Card>

          {job && <JobProgress job={job} onRetry={(j) => setJobId(j.id)} />}

          {result && (
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-[13px] text-ink-2">
                  <span className="font-medium text-ink">{result.voice_name}</span> · {languageLabel(result.language)} ·{" "}
                  <span className="num">
                    {formatDuration(result.duration_s)} in {result.stats.elapsed_s.toFixed(1)}s
                  </span>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" onClick={generate} disabled={busy}>
                    <RotateCcw /> Regenerate
                  </Button>
                  <ExportMenu onExport={(c) => api.exportGeneration(result.id, c)} />
                </div>
              </div>
              <Waveform url={api.generationAudioUrl(result.id)} autoPlay />
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card className="space-y-4 p-5">
            <Field label="Voice" htmlFor="voice">
              <VoicePicker
                id="voice"
                value={voiceId}
                onChange={(id) => {
                  setVoiceId(id);
                  const v = readyVoices.find((x) => x.id === id);
                  if (v) setLanguage(v.language);
                }}
              />
            </Field>
            <Field label="Language" htmlFor="language">
              <LanguagePicker id="language" value={language} onChange={setLanguage} />
            </Field>
            <Field
              label="Model"
              htmlFor="model"
              hint="Quality uses 1.7B; lightweight uses 0.6B. Only one model is loaded at a time."
            >
              <ModelPicker id="model" value={modelId} onChange={setModelId} />
            </Field>
            {voice && (
              <div className="border-t border-rule pt-4">
                <VoiceControls voice={voice} value={delivery} onChange={setDelivery} />
              </div>
            )}
            <Button
              size="lg"
              className="w-full"
              onClick={generate}
              loading={submitting}
              disabled={!voiceId || !language || !text.trim() || busy || !modelInstalled}
            >
              <Sparkles /> Generate speech
            </Button>
            {!modelInstalled && models && (
              <p className="text-xs text-amber">
                The selected model is not installed. <Link className="underline" to="/settings?tab=models">Install it</Link>.
              </p>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle>Recent</SectionTitle>
            {recent?.items.length ? (
              <ul className="space-y-2.5">
                {recent.items.map((g) => (
                  <li key={g.id} className="flex items-center gap-2.5">
                    <PlayButton id={g.id} url={api.generationAudioUrl(g.id)} />
                    <button
                      className="min-w-0 flex-1 text-left"
                      onClick={() => {
                        setText(g.text);
                        if (g.voice_id) setVoiceId(g.voice_id);
                        setLanguage(g.language);
                      }}
                      title="Load this text"
                    >
                      <p className="truncate text-[13px]">{g.text}</p>
                      <p className="text-[11.5px] text-ink-3">
                        {g.voice_name} · {formatDuration(g.duration_s)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-ink-3">Your generations will appear here.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
