import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Download,
  Mic,
  ShieldCheck,
  Sparkles,
  Wand2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { PageHeader } from "@/components/layout";
import { LanguagePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/form";
import { Callout, Card, Progress } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError, useModels } from "@/lib/hooks";
import type { VoiceMode } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

const MAX_INSTRUCTIONS = 1000;

/** The qualities Qwen3-TTS Voice Design understands from a written description. */
const TRAITS = [
  "Young adult",
  "Middle-aged",
  "Older",
  "Female",
  "Male",
  "Low-pitched",
  "High-pitched",
  "Deep and resonant",
  "Warm",
  "Bright and crisp",
  "Soft",
  "Slightly husky",
  "Slow, measured pace",
  "Brisk pace",
  "Calm",
  "Reassuring",
  "Energetic",
  "Playful",
  "Documentary narration",
  "Audiobook",
  "Commercial",
];

const EXAMPLES: Record<string, string> = {
  english:
    "Calm, slow-paced middle-aged male voice, deep and resonant, suited for documentary narration.",
  french:
    "Voix masculine calme, d'âge moyen, grave et chaleureuse, au rythme posé, adaptée à la narration d'un documentaire.",
  spanish:
    "Voz masculina tranquila, de mediana edad, grave y cálida, con un ritmo pausado, para narrar documentales.",
};

function ModeCard({
  active,
  icon,
  title,
  description,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-2xl border p-4 text-left transition-colors",
        active ? "border-ink bg-panel shadow-card" : "border-rule bg-panel/50 hover:bg-panel-2/50",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl [&_svg]:size-4",
          active ? "bg-accent text-accent-ink" : "bg-panel-2 text-ink-2",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 font-medium">
          {title}
          {active && <Check className="size-4 text-green" />}
        </span>
        <span className="mt-0.5 block text-[13px] leading-relaxed text-ink-3">{description}</span>
      </span>
    </button>
  );
}

/** Step 1 of either path: who the voice is (and, for cloning, who agreed to it). */
export function CloneVoice() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: models } = useModels();
  const [mode, setMode] = useState<VoiceMode>("clone");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState("english");
  const [speaker, setSpeaker] = useState("");
  const [scope, setScope] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);

  const designModel = useMemo(
    () => models?.find((m) => m.kind === "tts" && m.capability === "design"),
    [models],
  );
  const designReady = designModel?.status.state === "installed";
  const example = EXAMPLES[language] ?? EXAMPLES.english;

  const valid =
    name.trim().length > 0 &&
    (mode === "clone"
      ? speaker.trim() && scope.trim() && confirmed
      : instructions.trim().length > 0);

  function addTrait(trait: string) {
    const current = instructions.trim().replace(/[,\s]+$/, "");
    if (current.toLowerCase().includes(trait.toLowerCase())) return;
    const next = current ? `${current}, ${trait.toLowerCase()}` : trait;
    setInstructions(next.slice(0, MAX_INSTRUCTIONS));
  }

  async function create() {
    setBusy(true);
    try {
      const voice = await api.createVoice({
        name: name.trim(),
        description: description.trim(),
        language,
        mode,
        instructions: mode === "design" ? instructions.trim() : undefined,
        consent:
          mode === "clone"
            ? { confirmed, speaker: speaker.trim(), scope: scope.trim(), notes: notes.trim() }
            : undefined,
      });
      if (mode === "design") {
        // Voice the description straight away, so the profile opens on its takes.
        try {
          const job = await api.buildVoice(voice.id, {
            model_id: designModel?.id,
            language,
          });
          navigate(`/voices/${voice.id}`, { state: { designJobId: job.job_id } });
        } catch (err) {
          toastError(err, "Voice created, but the takes could not start");
          navigate(`/voices/${voice.id}`);
        }
      } else {
        navigate(`/voices/${voice.id}`);
      }
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
    } catch (err) {
      toastError(err, "Could not create the voice");
    } finally {
      setBusy(false);
    }
  }

  async function downloadDesignModel() {
    if (!designModel) return;
    try {
      await api.downloadModel(designModel.id);
      await queryClient.invalidateQueries({ queryKey: ["models"] });
    } catch (err) {
      toastError(err, "Download could not start");
    }
  }

  return (
    <>
      <PageHeader
        title="New voice"
        description="Clone a speaker from recordings, or design a new synthetic voice from a written description."
      />
      <div className="grid grid-cols-1 gap-6 rounded-[28px] bg-stage p-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:p-8">
        <div className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row">
            <ModeCard
              active={mode === "clone"}
              icon={<Mic />}
              title="Clone a recording"
              description="Recreate the voice of a real person from 30 seconds to 3 minutes of clean speech, with their permission."
              onClick={() => setMode("clone")}
            />
            <ModeCard
              active={mode === "design"}
              icon={<Wand2 />}
              title="Design from a description"
              description="Create a brand-new voice from text: age, pitch, timbre, pace and mood. No recording or consent needed."
              onClick={() => setMode("design")}
            />
          </div>

          <Card className="space-y-6 p-7">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Voice name" htmlFor="name">
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={mode === "clone" ? "e.g. Marie – warm narration" : "e.g. Deep documentary narrator"}
                  autoFocus
                />
              </Field>
              <Field
                label="Main language"
                htmlFor="lang"
                hint={mode === "clone" ? "The language of the reference recording." : "The language the voice will speak."}
              >
                <LanguagePicker id="lang" value={language} onChange={setLanguage} />
              </Field>
            </div>
            <Field label="Description" htmlFor="desc" hint="Optional: where the voice will be used, notes for later.">
              <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>

            {mode === "clone" ? (
              <div className="space-y-4 border-t border-rule pt-6">
                <div className="flex items-center gap-2 font-medium">
                  <ShieldCheck className="size-4" /> Speaker permission
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Speaker's full name" htmlFor="speaker">
                    <Input id="speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)} />
                  </Field>
                  <Field label="Permitted uses" htmlFor="scope" hint="What the speaker agreed their voice may be used for.">
                    <Input
                      id="scope"
                      value={scope}
                      onChange={(e) => setScope(e.target.value)}
                      placeholder="e.g. 1PAX project videos, internal presentations"
                    />
                  </Field>
                </div>
                <Field label="Notes" htmlFor="notes" hint="Optional: where the written consent is kept, expiry, restrictions.">
                  <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="min-h-16" />
                </Field>
                <label className="flex items-start gap-3 text-[14px] leading-relaxed text-ink-2">
                  <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} className="mt-0.5" />
                  <span>
                    I confirm that <strong>{speaker.trim() || "the speaker"}</strong> has authorised cloning their voice
                    for the uses above, and that I will use it only within that permission.
                  </span>
                </label>
              </div>
            ) : (
              <div className="space-y-4 border-t border-rule pt-6">
                <div className="flex items-center gap-2 font-medium">
                  <Sparkles className="size-4" /> Voice description
                </div>
                <Field
                  label="How should it sound?"
                  htmlFor="instructions"
                  hint="Describe age, gender, pitch, timbre, pace, mood and the kind of material it reads. English or Chinese descriptions work best; accents and dialects are not reliably controlled."
                >
                  <Textarea
                    id="instructions"
                    value={instructions}
                    onChange={(e) => setInstructions(e.target.value.slice(0, MAX_INSTRUCTIONS))}
                    className="min-h-28"
                    placeholder={example}
                  />
                </Field>
                <div className="flex items-center justify-between text-xs text-ink-3">
                  <button type="button" className="font-medium underline hover:text-ink" onClick={() => setInstructions(example)}>
                    Use an example
                  </button>
                  <span className="num">
                    {instructions.length} / {MAX_INSTRUCTIONS}
                  </span>
                </div>
                <div className="space-y-2">
                  <p className="text-[13px] font-medium">Add a quality</p>
                  <div className="flex flex-wrap gap-1.5">
                    {TRAITS.map((trait) => (
                      <button
                        key={trait}
                        type="button"
                        onClick={() => addTrait(trait)}
                        className="rounded-full border border-rule bg-panel px-2.5 py-1 text-[12.5px] text-ink-2 transition-colors hover:border-rule-strong hover:bg-panel-2 hover:text-ink"
                      >
                        + {trait}
                      </button>
                    ))}
                  </div>
                </div>
                <p className="text-xs leading-relaxed text-ink-3">
                  Be specific and audible: “deep, unhurried, slightly husky” works better than “nice”. Ask for a voice
                  type, not a particular person's voice.
                </p>
              </div>
            )}

            {mode === "design" && designModel && !designReady && (
              <Callout tone={designModel.status.state === "failed" ? "amber" : "blue"}>
                <p className="mb-2 font-medium">
                  {designModel.status.state === "downloading"
                    ? `Downloading ${designModel.label} · ${formatBytes(designModel.status.downloaded_bytes ?? 0)}${designModel.status.total_bytes ? ` of ${formatBytes(designModel.status.total_bytes)}` : ""}`
                    : `${designModel.label} (~${designModel.approx_download_gb} GB, one-time download) is needed to design voices.`}
                </p>
                {designModel.status.state === "downloading" ? (
                  <Progress
                    value={
                      designModel.status.total_bytes
                        ? ((designModel.status.downloaded_bytes ?? 0) / designModel.status.total_bytes) * 100
                        : null
                    }
                  />
                ) : (
                  <Button size="sm" onClick={downloadDesignModel}>
                    <Download /> {designModel.status.state === "failed" ? "Resume download" : "Download"}
                  </Button>
                )}
              </Callout>
            )}

            <div className="flex justify-end">
              <Button
                onClick={create}
                disabled={!valid || (mode === "design" && !designReady)}
                loading={busy}
              >
                {mode === "clone" ? "Continue to recordings" : "Create and preview 3 takes"}
              </Button>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          {mode === "clone" ? (
            <Callout tone="neutral" className="border border-rule bg-panel shadow-card">
              <p className="mb-1 font-medium text-ink">What makes a good reference</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>30 seconds to 3 minutes of one person speaking naturally, in one file or several</li>
                <li>A quiet room, no music, no other voices</li>
                <li>Even distance from the microphone, no clipping</li>
                <li>The same style you want to generate (calm narration, lively promo…)</li>
                <li>No transcript needed: recordings are transcribed on this Mac</li>
              </ul>
            </Callout>
          ) : (
            <Callout tone="neutral" className="border border-rule bg-panel shadow-card">
              <p className="mb-1 font-medium text-ink">What the description can shape</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Gender and rough age</li>
                <li>Pitch and vocal timbre: deep, warm, bright, husky…</li>
                <li>Speaking pace and intonation</li>
                <li>Emotion and delivery</li>
                <li>The material it suits: documentary, audiobook, commercial…</li>
              </ul>
              <p className="mt-2 text-ink-3">
                Each description is read three times with different seeds, so you can pick the take that fits best.
              </p>
            </Callout>
          )}
          <Callout tone="blue">
            {mode === "clone"
              ? "Recordings, transcripts and the cloned voice never leave this Mac. Deleting the voice removes the recordings and everything derived from them."
              : "A designed voice belongs to no real speaker, so there is no consent record to collect. It is generated entirely on this Mac, and the description stays with the voice profile."}
          </Callout>
        </div>
      </div>
    </>
  );
}
