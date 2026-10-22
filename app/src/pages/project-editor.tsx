import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  FileText,
  GripVertical,
  Layers,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { announceExport } from "@/components/export-menu";
import { JobBadge } from "@/components/job-progress";
import { PlayButton } from "@/components/mini-player";
import { LanguagePicker, ModelPicker, VoicePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/form";
import {
  Badge,
  Callout,
  Card,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownMenu,
  DropdownSeparator,
  DropdownTrigger,
  Progress,
  Skeleton,
  Tabs,
  Tooltip,
} from "@/components/ui/misc";
import { Select } from "@/components/ui/select";
import { Waveform } from "@/components/waveform";
import { api } from "@/lib/api";
import { toastError, useSettings, useVoices } from "@/lib/hooks";
import type { Project, Segment } from "@/lib/types";
import { cn, formatDate, formatDuration } from "@/lib/utils";

const ACTIVE = new Set(["queued", "loading", "synthesizing", "processing"]);

function SegmentRow({
  project,
  segment,
  index,
  onProject,
}: {
  project: Project;
  segment: Segment;
  index: number;
  onProject: (p: Project) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: segment.id });
  const [text, setText] = useState(segment.text);
  const [pause, setPause] = useState(String(segment.pause_after_ms));
  const textarea = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setText(segment.text), [segment.text]);
  useEffect(() => setPause(String(segment.pause_after_ms)), [segment.pause_after_ms]);
  useEffect(() => {
    const el = textarea.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight}px`;
    }
  }, [text]);

  const job = segment.job;
  const running = !!job && ACTIVE.has(job.status);
  const active = segment.takes.find((t) => t.id === segment.active_generation_id);

  async function call(fn: () => Promise<Project | unknown>) {
    try {
      const result = await fn();
      if (result && typeof result === "object" && "segments" in result) onProject(result as Project);
    } catch (err) {
      toastError(err);
    }
  }

  const saveText = () => {
    if (text.trim() && text.trim() !== segment.text) {
      void call(() => api.updateSegment(project.id, segment.id, { text: text.trim() }));
    } else setText(segment.text);
  };
  const savePause = () => {
    const ms = Math.max(0, Math.min(10000, Math.round(Number(pause) || 0)));
    if (ms !== segment.pause_after_ms) void call(() => api.updateSegment(project.id, segment.id, { pause_after_ms: ms }));
    else setPause(String(segment.pause_after_ms));
  };

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn("group flex gap-3 border-b border-rule bg-panel px-3 py-3 last:border-b-0", isDragging && "relative z-10 shadow-pop")}
    >
      <div className="flex w-9 shrink-0 flex-col items-center gap-1 pt-1">
        <button className="cursor-grab text-ink-3 hover:text-ink active:cursor-grabbing" {...attributes} {...listeners} aria-label="Drag to reorder">
          <GripVertical className="size-4" />
        </button>
        <span className="num text-[11px] text-ink-3">{index + 1}</span>
      </div>
      <div className="min-w-0 flex-1">
        <textarea
          ref={textarea}
          value={text}
          rows={1}
          onChange={(e) => setText(e.target.value)}
          onBlur={saveText}
          className="w-full resize-none rounded-lg border border-transparent bg-transparent px-2 py-1 text-[14px] leading-relaxed outline-none hover:border-rule focus:border-ink"
        />
        <div className="mt-1 flex flex-wrap items-center gap-2 px-2">
          {job && (running || job.status === "failed") ? (
            <JobBadge job={job} />
          ) : active ? (
            <Badge tone={segment.active_take_stale ? "amber" : "green"}>
              {segment.active_take_stale ? "Text changed · regenerate" : `${formatDuration(active.duration_s)}`}
            </Badge>
          ) : (
            <Badge>No audio</Badge>
          )}
          {job?.status === "failed" && <span className="truncate text-xs text-red">{job.error_message}</span>}
          {segment.takes.length > 1 && (
            <Select
              size="sm"
              className="h-6 w-auto rounded-full border-0 bg-panel-2 px-2 text-[11.5px]"
              value={segment.active_generation_id ?? undefined}
              onValueChange={(id) => void call(() => api.updateSegment(project.id, segment.id, { active_generation_id: id }))}
              options={segment.takes.map((t, i) => ({
                value: t.id,
                label: `Take ${i + 1}`,
                description: `${formatDuration(t.duration_s)} · ${formatDate(t.created_at)}${t.text !== segment.text ? " · old text" : ""}`,
              }))}
            />
          )}
          <span className="ml-auto flex items-center gap-1 text-xs text-ink-3">
            Pause after
            <input
              value={pause}
              onChange={(e) => setPause(e.target.value.replace(/[^0-9]/g, ""))}
              onBlur={savePause}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              className="num w-14 rounded-md border border-rule bg-panel px-1.5 py-0.5 text-right text-xs text-ink outline-none focus:border-ink"
            />
            ms
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-start gap-1 pt-0.5">
        <PlayButton id={segment.active_generation_id ?? segment.id} url={active ? api.generationAudioUrl(active.id) : null} />
        {running ? (
          <Tooltip content="Cancel">
            <Button size="icon-sm" variant="ghost" onClick={() => void call(() => api.cancelJob(job!.id))}>
              <X />
            </Button>
          </Tooltip>
        ) : (
          <Tooltip content={active ? "Regenerate (keeps the current take)" : "Generate"}>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => void call(() => api.generateProject(project.id, { segment_ids: [segment.id], only_missing: false }))}
            >
              {active ? <RotateCcw /> : <Sparkles />}
            </Button>
          </Tooltip>
        )}
        <DropdownMenu>
          <DropdownTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label="Segment actions">
              <MoreHorizontal />
            </Button>
          </DropdownTrigger>
          <DropdownContent>
            <DropdownItem onSelect={() => void call(() => api.addSegment(project.id, { text: "New segment.", after_segment_id: segment.id }))}>
              <Plus /> Add segment below
            </DropdownItem>
            <DropdownSeparator />
            <DropdownItem danger onSelect={() => void call(() => api.deleteSegment(project.id, segment.id))}>
              <Trash2 /> Delete segment
            </DropdownItem>
          </DropdownContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

function ScriptDialog({ project, open, onOpenChange, onProject }: { project: Project; open: boolean; onOpenChange: (o: boolean) => void; onProject: (p: Project) => void }) {
  const [script, setScript] = useState(project.script);
  const [mode, setMode] = useState<"paragraph" | "sentence">("paragraph");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setScript(project.segments.length ? project.segments.map((s) => s.text).join("\n\n") : project.script);
  }, [open, project]);
  async function apply() {
    setBusy(true);
    try {
      onProject(await api.resegment(project.id, script, mode));
      onOpenChange(false);
    } catch (err) {
      toastError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Edit script"
      description="Segments whose text stays exactly the same keep their takes. Changed or removed segments lose theirs."
      className="w-[min(760px,94vw)]"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={apply} loading={busy}>
            Apply
          </Button>
        </>
      }
    >
      <Textarea value={script} onChange={(e) => setScript(e.target.value)} className="min-h-[360px]" />
      <div className="mt-3 flex items-center gap-3 text-[13px]">
        <span className="text-ink-2">Split into</span>
        <Tabs
          value={mode}
          onValueChange={(v) => setMode(v as "paragraph" | "sentence")}
          tabs={[
            { value: "paragraph", label: "Paragraphs" },
            { value: "sentence", label: "Sentences" },
          ]}
        />
      </div>
    </Dialog>
  );
}

function ExportDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { data: settings } = useSettings();
  const [format, setFormat] = useState<"wav" | "mp3">("wav");
  const [bitrate, setBitrate] = useState("320");
  const [rate, setRate] = useState("native");
  const [mode, setMode] = useState<"combined" | "segments" | "both">("combined");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (settings) {
      setFormat(settings.default_export_format);
      setBitrate(String(settings.default_mp3_bitrate));
    }
  }, [settings]);
  async function run() {
    setBusy(true);
    try {
      announceExport(
        await api.exportProject(project.id, {
          format,
          bitrate: Number(bitrate),
          sample_rate: rate === "native" ? null : Number(rate),
          mode,
        }),
      );
      onOpenChange(false);
    } catch (err) {
      toastError(err, "Export failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Export project"
      description={`Files are written to ${settings?.output_dir ?? "the output folder"}/${project.name}.`}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={run} loading={busy}>
            <Download /> Export
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What">
          <Select
            value={mode}
            onValueChange={(v) => setMode(v as typeof mode)}
            options={[
              { value: "combined", label: "One combined file" },
              { value: "segments", label: "One file per segment" },
              { value: "both", label: "Both" },
            ]}
          />
        </Field>
        <Field label="Format">
          <Select
            value={format}
            onValueChange={(v) => setFormat(v as "wav" | "mp3")}
            options={[
              { value: "wav", label: "WAV (lossless)" },
              { value: "mp3", label: "MP3" },
            ]}
          />
        </Field>
        {format === "mp3" && (
          <Field label="Bitrate">
            <Select
              value={bitrate}
              onValueChange={setBitrate}
              options={[
                { value: "320", label: "320 kbps" },
                { value: "192", label: "192 kbps" },
              ]}
            />
          </Field>
        )}
        <Field label="Sample rate">
          <Select
            value={rate}
            onValueChange={setRate}
            options={[
              { value: "native", label: format === "mp3" ? "44.1 kHz (MP3 default)" : "24 kHz (model native)" },
              { value: "44100", label: "44.1 kHz" },
              { value: "48000", label: "48 kHz (video)" },
            ]}
          />
        </Field>
      </div>
    </Dialog>
  );
}

export function ProjectEditor() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { data: project, isLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.project(projectId),
    refetchInterval: (q) => (q.state.data?.segments.some((s) => s.job && ACTIVE.has(s.job.status)) ? 1000 : false),
  });
  const { data: voices } = useVoices();
  const [scriptOpen, setScriptOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [name, setName] = useState("");
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  useEffect(() => {
    if (project) setName(project.name);
  }, [project?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  if (isLoading) return <Skeleton className="h-96" />;
  if (!project) return <Callout tone="red">This project could not be loaded.</Callout>;

  const setProject = (p: Project) => {
    queryClient.setQueryData(["project", projectId], p);
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
  };
  const update = async (body: Partial<Project>) => {
    try {
      setProject(await api.updateProject(project.id, body));
    } catch (err) {
      toastError(err);
    }
  };
  const running = project.segments.filter((s) => s.job && ACTIVE.has(s.job.status)).length;
  const missing = project.segments.filter((s) => !s.active_generation_id || s.active_take_stale).length;
  const projectVoice = voices?.find((v) => v.id === project.voice_id);
  const modelCapability = projectVoice?.mode ?? "clone";

  async function generateMissing() {
    try {
      const jobs = await api.generateProject(project!.id, { only_missing: true });
      if (!jobs.length) return;
      await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    } catch (err) {
      toastError(err, "Could not queue the segments");
    }
  }

  async function cancelAll() {
    await Promise.all(project!.segments.filter((s) => s.job && ACTIVE.has(s.job.status)).map((s) => api.cancelJob(s.job!.id).catch(() => null)));
    await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
  }

  async function preview() {
    setPreviewing(true);
    try {
      const blob = await api.previewProject(project!.id);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (err) {
      toastError(err, "Cannot preview yet");
    } finally {
      setPreviewing(false);
    }
  }

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const ids = project!.segments.map((s) => s.id);
    const next = arrayMove(ids, ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
    queryClient.setQueryData(["project", projectId], {
      ...project!,
      segments: next.map((id) => project!.segments.find((s) => s.id === id)!),
    });
    api.reorder(project!.id, next).then(setProject).catch(toastError);
  }

  return (
    <>
      <div className="mb-6">
        <Link to="/projects" className="mb-3 inline-flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink">
          <ArrowLeft className="size-3.5" /> Projects
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name.trim() && name !== project.name && void update({ name: name.trim() })}
            className="h-auto w-auto min-w-0 flex-1 border-transparent bg-transparent px-0 text-2xl font-semibold tracking-tight hover:border-rule focus:px-2"
          />
          <Button variant="outline" size="sm" onClick={() => setScriptOpen(true)}>
            <FileText /> Edit script
          </Button>
          <Button variant="outline" size="sm" onClick={preview} loading={previewing} disabled={missing > 0 && project.generated_count === 0}>
            <Layers /> Preview
          </Button>
          <Button variant="outline" size="sm" onClick={() => setExportOpen(true)} disabled={project.generated_count === 0}>
            <Download /> Export
          </Button>
          {running ? (
            <Button size="sm" variant="secondary" onClick={cancelAll}>
              <X /> Cancel {running} queued
            </Button>
          ) : (
            <Button size="sm" onClick={generateMissing} disabled={!project.voice_id || missing === 0}>
              <Sparkles /> {missing ? `Generate ${missing} missing` : "All generated"}
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          {previewUrl && (
            <Card className="p-4">
              <div className="mb-2 flex items-center justify-between text-[13px]">
                <span className="font-medium">Assembled preview</span>
                <button className="text-ink-3 hover:text-ink" onClick={() => setPreviewUrl(null)}>
                  Close
                </button>
              </div>
              <Waveform url={previewUrl} autoPlay />
            </Card>
          )}
          {project.segments.length ? (
            <Card className="overflow-hidden p-0">
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={project.segments.map((s) => s.id)} strategy={verticalListSortingStrategy}>
                  {project.segments.map((segment, index) => (
                    <SegmentRow key={segment.id} project={project} segment={segment} index={index} onProject={setProject} />
                  ))}
                </SortableContext>
              </DndContext>
            </Card>
          ) : (
            <Callout>
              This project has no segments yet.{" "}
              <button className="font-medium underline" onClick={() => setScriptOpen(true)}>
                Add the script
              </button>
              .
            </Callout>
          )}
          {project.segments.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => api.addSegment(project.id, { text: "New segment." }).then(setProject).catch(toastError)}>
              <Plus /> Add segment
            </Button>
          )}
        </div>

        <div className="space-y-4">
          <Card className="space-y-4 p-5">
            <Field label="Voice">
              <VoicePicker value={project.voice_id} onChange={(voice_id) => void update({ voice_id })} />
            </Field>
            <Field label="Language">
              <LanguagePicker value={project.language} onChange={(language) => void update({ language })} />
            </Field>
            <Field label="Model">
              <ModelPicker
                value={project.model_id}
                onChange={(model_id) => void update({ model_id })}
                capability={modelCapability}
              />
            </Field>
            <p className="text-xs text-ink-3">Changing these affects segments generated from now on; existing takes stay as they are.</p>
          </Card>
          <Card className="space-y-3 p-5 text-[13px]">
            <div className="flex justify-between">
              <span className="text-ink-2">Segments with audio</span>
              <span className="num font-medium">
                {project.generated_count} / {project.segment_count}
              </span>
            </div>
            <Progress value={project.segment_count ? (project.generated_count / project.segment_count) * 100 : 0} />
            <div className="flex justify-between">
              <span className="text-ink-2">Speech duration</span>
              <span className="num font-medium">{formatDuration(project.duration_s)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-2">With pauses</span>
              <span className="num font-medium">
                {formatDuration(project.duration_s + project.segments.slice(0, -1).reduce((sum, s) => sum + s.pause_after_ms / 1000, 0))}
              </span>
            </div>
          </Card>
          <Card className="space-y-3 p-5">
            <p className="text-[13px] font-medium">Default pauses</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Sentence (ms)">
                <Input
                  type="number"
                  min={0}
                  max={10000}
                  defaultValue={project.default_pause_ms}
                  onBlur={(e) => Number(e.target.value) !== project.default_pause_ms && void update({ default_pause_ms: Number(e.target.value) })}
                />
              </Field>
              <Field label="Paragraph (ms)">
                <Input
                  type="number"
                  min={0}
                  max={10000}
                  defaultValue={project.paragraph_pause_ms}
                  onBlur={(e) => Number(e.target.value) !== project.paragraph_pause_ms && void update({ paragraph_pause_ms: Number(e.target.value) })}
                />
              </Field>
            </div>
            <p className="text-xs text-ink-3">Used for new segments and when the script is split again.</p>
          </Card>
          <DropdownMenu>
            <DropdownTrigger asChild>
              <Button variant="ghost" size="sm" className="w-full">
                <MoreHorizontal /> More
              </Button>
            </DropdownTrigger>
            <DropdownContent align="start">
              <DropdownLabel>Regenerate</DropdownLabel>
              <DropdownItem
                onSelect={() =>
                  api
                    .generateProject(project.id, { segment_ids: project.segments.map((s) => s.id), only_missing: false })
                    .then(() => queryClient.invalidateQueries({ queryKey: ["project", projectId] }))
                    .catch(toastError)
                }
                disabled={!project.voice_id}
              >
                <RotateCcw /> New takes for every segment
              </DropdownItem>
            </DropdownContent>
          </DropdownMenu>
        </div>
      </div>

      <ScriptDialog project={project} open={scriptOpen} onOpenChange={setScriptOpen} onProject={setProject} />
      <ExportDialog project={project} open={exportOpen} onOpenChange={setExportOpen} />
    </>
  );
}
