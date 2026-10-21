import { useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { PageHeader } from "@/components/layout";
import { LanguagePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Checkbox, Field, Input, Textarea } from "@/components/ui/form";
import { Card, Callout } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";

/** Step 1 of cloning: who the voice belongs to and what they agreed to. */
export function CloneVoice() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [language, setLanguage] = useState("english");
  const [speaker, setSpeaker] = useState("");
  const [scope, setScope] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);

  const valid = name.trim() && speaker.trim() && scope.trim() && confirmed;

  async function create() {
    setBusy(true);
    try {
      const voice = await api.createVoice({
        name: name.trim(),
        description: description.trim(),
        language,
        consent: { confirmed, speaker: speaker.trim(), scope: scope.trim(), notes: notes.trim() },
      });
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
      navigate(`/voices/${voice.id}`);
    } catch (err) {
      toastError(err, "Could not create the voice");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Voice Cloning"
        description="Create a voice profile, add up to 3 minutes of recordings, then pick the best of three takes."
      />
      <div className="grid grid-cols-1 gap-6 rounded-[28px] bg-stage p-6 lg:grid-cols-[minmax(0,1fr)_300px] lg:p-8">
        <Card className="space-y-6 p-7">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Voice name" htmlFor="name">
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Marie – warm narration" autoFocus />
            </Field>
            <Field label="Main language" htmlFor="lang" hint="The language of the reference recording.">
              <LanguagePicker id="lang" value={language} onChange={setLanguage} />
            </Field>
          </div>
          <Field label="Description" htmlFor="desc" hint="Optional: tone, intended use, microphone…">
            <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>

          <div className="space-y-4 border-t border-rule pt-6">
            <div className="flex items-center gap-2 font-medium">
              <ShieldCheck className="size-4" /> Speaker permission
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Speaker's full name" htmlFor="speaker">
                <Input id="speaker" value={speaker} onChange={(e) => setSpeaker(e.target.value)} />
              </Field>
              <Field label="Permitted uses" htmlFor="scope" hint="What the speaker agreed their voice may be used for.">
                <Input id="scope" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="e.g. 1PAX project videos, internal presentations" />
              </Field>
            </div>
            <Field label="Notes" htmlFor="notes" hint="Optional: where the written consent is kept, expiry, restrictions.">
              <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} className="min-h-16" />
            </Field>
            <label className="flex items-start gap-3 text-[14px] leading-relaxed text-ink-2">
              <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} className="mt-0.5" />
              <span>
                I confirm that <strong>{speaker.trim() || "the speaker"}</strong> has authorised cloning their voice for the
                uses above, and that I will use it only within that permission.
              </span>
            </label>
          </div>

          <div className="flex justify-end">
            <Button onClick={create} disabled={!valid} loading={busy}>
              Continue to recordings
            </Button>
          </div>
        </Card>

        <div className="space-y-4">
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
          <Callout tone="blue">
            Recordings, transcripts and the cloned voice never leave this Mac. Deleting the voice removes the recordings
            and everything derived from them.
          </Callout>
        </div>
      </div>
    </>
  );
}
