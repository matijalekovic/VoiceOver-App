import { useQueryClient } from "@tanstack/react-query";
import { AudioLines, Download, MoreHorizontal, Pencil, Plus, Trash2, Upload, UserRound } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { toast } from "sonner";
import { Orb } from "@/components/brand";
import { announceExport } from "@/components/export-menu";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Checkbox, Label } from "@/components/ui/form";
import {
  Badge,
  Card,
  DropdownContent,
  DropdownItem,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
  EmptyState,
  Skeleton,
} from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError, useVoices } from "@/lib/hooks";
import type { Voice } from "@/lib/types";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

export function previewUrl(voice: Voice): { id: string; url: string } | null {
  if (voice.preferred_sample_generation_id) {
    return { id: voice.preferred_sample_generation_id, url: api.generationAudioUrl(voice.preferred_sample_generation_id) };
  }
  const ref = voice.references.find((r) => r.id === voice.primary_reference_id);
  return ref ? { id: ref.id, url: api.referenceAudioUrl(voice.id, ref.id, "reference", ref.updated_at) } : null;
}

export function DeleteVoiceDialog({
  voice,
  onClose,
  onDeleted,
}: {
  voice: Voice | null;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const queryClient = useQueryClient();
  const [alsoAudio, setAlsoAudio] = useState(false);
  const [busy, setBusy] = useState(false);
  async function confirm() {
    if (!voice) return;
    setBusy(true);
    try {
      await api.deleteVoice(voice.id, alsoAudio);
      await queryClient.invalidateQueries();
      toast.success(`Deleted “${voice.name}”`);
      onClose();
      onDeleted?.();
    } catch (err) {
      toastError(err, "Could not delete the voice");
    } finally {
      setBusy(false);
    }
  }
  return (
    <ConfirmDialog
      open={!!voice}
      onOpenChange={(open) => !open && onClose()}
      title={`Delete “${voice?.name}”?`}
      description="The reference recordings, transcripts and everything derived from them are removed from this Mac. This cannot be undone."
      onConfirm={confirm}
      busy={busy}
    >
      <label className="flex items-center gap-2.5 text-[13px]">
        <Checkbox checked={alsoAudio} onCheckedChange={(v) => setAlsoAudio(v === true)} />
        <Label>Also delete speech generated with this voice ({voice?.generation_count ?? 0} clips, excluding project takes)</Label>
      </label>
    </ConfirmDialog>
  );
}

function VoiceCard({ voice, onDelete }: { voice: Voice; onDelete: (v: Voice) => void }) {
  const navigate = useNavigate();
  const preview = previewUrl(voice);
  const primary = voice.references.find((r) => r.id === voice.primary_reference_id);
  async function exportVoice() {
    try {
      announceExport(await api.exportVoice(voice.id));
    } catch (err) {
      toastError(err, "Export failed");
    }
  }
  return (
    <Card className="group flex flex-col p-4 transition-colors hover:bg-panel-2/40">
      <div className="flex items-start gap-3">
        <Orb size={44} voiceId={voice.id} still />
        <div className="min-w-0 flex-1">
          <Link to={`/voices/${voice.id}`} className="block truncate font-semibold hover:underline">
            {voice.name}
          </Link>
          <p className="truncate text-xs text-ink-3">{voice.description || `Speaker: ${voice.consent.speaker}`}</p>
        </div>
        <DropdownMenu>
          <DropdownTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Voice actions">
              <MoreHorizontal />
            </Button>
          </DropdownTrigger>
          <DropdownContent>
            <DropdownItem onSelect={() => navigate(`/generate?voice=${voice.id}`)} disabled={voice.status !== "ready"}>
              <AudioLines /> Use in Text to Speech
            </DropdownItem>
            <DropdownItem onSelect={() => navigate(`/voices/${voice.id}`)}>
              <Pencil /> Edit
            </DropdownItem>
            <DropdownItem onSelect={exportVoice}>
              <Download /> Export backup
            </DropdownItem>
            <DropdownSeparator />
            <DropdownItem danger onSelect={() => onDelete(voice)}>
              <Trash2 /> Delete
            </DropdownItem>
          </DropdownContent>
        </DropdownMenu>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {voice.status === "draft" ? <Badge tone="amber">Draft</Badge> : <Badge tone="green">Ready</Badge>}
        <Badge>{languageLabel(voice.language)}</Badge>
        {primary && <Badge>{formatDuration(primary.duration_s)} reference</Badge>}
      </div>
      <div className="mt-4 flex items-center justify-between">
        <span className="text-xs text-ink-3">Updated {formatDate(voice.updated_at)}</span>
        {voice.status === "draft" ? (
          <Button size="sm" variant="outline" onClick={() => navigate(`/voices/${voice.id}`)}>
            Finish setup
          </Button>
        ) : (
          preview && <PlayButton id={preview.id} url={preview.url} label="Preview" />
        )}
      </div>
    </Card>
  );
}

export function Voices() {
  const queryClient = useQueryClient();
  const { data: voices, isLoading } = useVoices();
  const [deleting, setDeleting] = useState<Voice | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function importVoice(file: File) {
    try {
      const voice = await api.importVoice(file);
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
      toast.success(`Imported “${voice.name}”`);
    } catch (err) {
      toastError(err, "Import failed");
    }
  }

  return (
    <>
      <PageHeader
        title="Voices"
        description="Voice profiles cloned from authorised recordings. They stay on this Mac."
        actions={
          <>
            <input
              ref={fileInput}
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void importVoice(file);
                e.target.value = "";
              }}
            />
            <Button variant="outline" size="sm" onClick={() => fileInput.current?.click()}>
              <Upload /> Import
            </Button>
            <Button asChild size="sm">
              <Link to="/clone">
                <Plus /> Clone voice
              </Link>
            </Button>
          </>
        }
      />
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : voices?.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {voices.map((v) => (
            <VoiceCard key={v.id} voice={v} onDelete={setDeleting} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<UserRound />}
          title="No voices yet"
          action={
            <Button asChild>
              <Link to="/clone">Clone your first voice</Link>
            </Button>
          }
        >
          A voice is cloned from 10–30 seconds of clean speech and its exact transcript.
        </EmptyState>
      )}
      <DeleteVoiceDialog voice={deleting} onClose={() => setDeleting(null)} />
    </>
  );
}
