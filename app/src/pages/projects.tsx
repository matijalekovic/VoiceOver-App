import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { PageHeader } from "@/components/layout";
import { LanguagePicker, ModelPicker, VoicePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Card, EmptyState, Progress, Skeleton, Tabs } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError, usePreferredModelId, useVoices } from "@/lib/hooks";
import type { Project } from "@/lib/types";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: voices } = useVoices();
  const [name, setName] = useState("");
  const [script, setScript] = useState("");
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [language, setLanguage] = useState("english");
  const [modelId, setModelId] = useState<string | null>(null);
  const [segmentation, setSegmentation] = useState<"paragraph" | "sentence">("paragraph");
  const [busy, setBusy] = useState(false);

  const preferredModelId = usePreferredModelId();
  useEffect(() => {
    if (!modelId && preferredModelId) setModelId(preferredModelId);
  }, [modelId, preferredModelId]);

  async function create() {
    setBusy(true);
    try {
      const project = await api.createProject({
        name: name.trim(),
        script,
        voice_id: voiceId,
        language,
        model_id: modelId ?? undefined,
        segmentation,
      });
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      onOpenChange(false);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      toastError(err, "Could not create the project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New project"
      description="Paste a long script. It is split into segments you can generate, edit and regenerate one by one."
      className="w-[min(720px,94vw)]"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={create} disabled={!name.trim()} loading={busy}>
            Create project
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Harbour housing – film narration" autoFocus />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Voice">
            <VoicePicker
              value={voiceId}
              onChange={(id) => {
                setVoiceId(id);
                const v = voices?.find((x) => x.id === id);
                if (v) setLanguage(v.language);
              }}
            />
          </Field>
          <Field label="Language">
            <LanguagePicker value={language} onChange={setLanguage} />
          </Field>
          <Field label="Model">
            <ModelPicker value={modelId} onChange={setModelId} />
          </Field>
        </div>
        <Field label="Script" hint="Blank lines separate paragraphs; a longer pause is placed after each paragraph.">
          <Textarea value={script} onChange={(e) => setScript(e.target.value)} className="min-h-56" />
        </Field>
        <div className="flex items-center gap-3 text-[13px]">
          <span className="text-ink-2">Split into</span>
          <Tabs
            value={segmentation}
            onValueChange={(v) => setSegmentation(v as "paragraph" | "sentence")}
            tabs={[
              { value: "paragraph", label: "Paragraphs" },
              { value: "sentence", label: "Sentences" },
            ]}
          />
        </div>
      </div>
    </Dialog>
  );
}

export function Projects() {
  const queryClient = useQueryClient();
  const { data: projects, isLoading } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Project | null>(null);

  async function remove() {
    if (!deleting) return;
    try {
      await api.deleteProject(deleting.id);
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      setDeleting(null);
    } catch (err) {
      toastError(err, "Could not delete");
    }
  }

  return (
    <>
      <PageHeader
        title="Projects"
        description="Long-form voiceovers built from segments, with takes you can compare and replace."
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus /> New project
          </Button>
        }
      />
      {isLoading ? (
        <Skeleton className="h-48" />
      ) : projects?.length ? (
        <Card className="divide-y divide-rule">
          {projects.map((p) => (
            <div key={p.id} className="flex items-center gap-4 px-5 py-4">
              <FolderKanban className="size-5 text-ink-3" />
              <Link to={`/projects/${p.id}`} className="min-w-0 flex-1">
                <p className="truncate font-medium hover:underline">{p.name}</p>
                <p className="text-xs text-ink-3">
                  {languageLabel(p.language)} · {p.segment_count} segments · updated {formatDate(p.updated_at)}
                </p>
              </Link>
              <div className="w-40">
                <Progress value={p.segment_count ? (p.generated_count / p.segment_count) * 100 : 0} />
                <p className="num mt-1 text-right text-xs text-ink-3">
                  {p.generated_count}/{p.segment_count} · {formatDuration(p.duration_s)}
                </p>
              </div>
              <Button variant="ghost" size="icon-sm" onClick={() => setDeleting(p)} aria-label="Delete project">
                <Trash2 />
              </Button>
            </div>
          ))}
        </Card>
      ) : (
        <EmptyState
          icon={<FolderKanban />}
          title="No projects yet"
          action={<Button onClick={() => setCreating(true)}>New project</Button>}
        >
          Projects are for scripts longer than a few paragraphs: narration, explainer films, presentations.
        </EmptyState>
      )}
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.name}”?`}
        description="The script, all segments and every generated take are removed. Exported files in your output folder are kept."
        onConfirm={remove}
      />
    </>
  );
}
