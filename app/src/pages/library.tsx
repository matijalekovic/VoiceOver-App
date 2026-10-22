import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Copy, Download, Library as LibraryIcon, Search, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Link, useNavigate } from "react-router";
import { announceExport, EXPORT_CHOICES, type ExportChoice, ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { VoicePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Badge, Card, EmptyState, Skeleton, Tooltip } from "@/components/ui/misc";
import { Waveform } from "@/components/waveform";
import { api } from "@/lib/api";
import { toastError, useModels } from "@/lib/hooks";
import type { Generation } from "@/lib/types";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

const PAGE = 30;

function Setting({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-ink-3">{label}</dt>
      <dd className="mt-0.5 text-[13.5px] text-ink">{children}</dd>
    </div>
  );
}

/** One take in full: listen, read the whole text, see how it was made, export it. */
function TakeDialog({ take, onClose, onDelete }: { take: Generation; onClose: () => void; onDelete: () => void }) {
  const navigate = useNavigate();
  const { data: models } = useModels();
  const [exporting, setExporting] = useState<string | null>(null);
  const p = take.params;
  const fit = take.stats.fit;
  const model = models?.find((m) => m.id === take.model_id);

  async function exportAs(label: string, choice: ExportChoice) {
    setExporting(label);
    try {
      announceExport(await api.exportGeneration(take.id, choice));
    } catch (err) {
      toastError(err, "Export failed");
    } finally {
      setExporting(null);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={take.voice_name}
      description={`${languageLabel(take.language)} · ${formatDuration(take.duration_s)} · ${formatDate(take.created_at)}`}
      className="w-[min(760px,94vw)]"
      footer={
        <>
          <Button variant="danger-ghost" size="sm" className="mr-auto" onClick={onDelete}>
            <Trash2 /> Delete
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!take.voice_id}
            onClick={() =>
              navigate("/generate", {
                state: { text: take.text, voice_id: take.voice_id, language: take.language, tone: p.tone ?? "" },
              })
            }
          >
            <Sparkles /> Open in Text to Speech
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        <Waveform url={api.generationAudioUrl(take.id)} />

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[14px] font-medium">Text</h3>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => navigator.clipboard.writeText(take.text).then(() => toast.success("Text copied"))}
            >
              <Copy /> Copy
            </Button>
          </div>
          <p className="selectable max-h-56 overflow-y-auto whitespace-pre-wrap rounded-xl bg-panel-2 px-4 py-3 text-[14px] leading-relaxed">
            {take.text}
          </p>
        </section>

        <section>
          <h3 className="mb-2 text-[14px] font-medium">Settings used</h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            <Setting label="Voice">{take.voice_name}</Setting>
            <Setting label="Language">{languageLabel(take.language)}</Setting>
            <Setting label="Model">{model ? `${model.label}` : take.model_id}</Setting>
            <Setting label="Cloning">
              {p.fingerprint ? "Voice fingerprint (native pronunciation, follows tone)" : "From the recording"}
            </Setting>
            <Setting label="Tone">{p.tone || "None"}</Setting>
            <Setting label="Expressiveness">{p.expressiveness != null ? `${Math.round(p.expressiveness * 100)}%` : "–"}</Setting>
            <Setting label="Speed">{fit ? `${fit.speed.toFixed(2)}× (fitted)` : p.speed != null ? `${p.speed.toFixed(2)}×` : "–"}</Setting>
            <Setting label="Pitch">{p.pitch ? `${p.pitch > 0 ? "+" : "−"}${Math.abs(p.pitch)} st` : "0"}</Setting>
            <Setting label="Seed">
              <span className="num selectable">{p.seed ?? "–"}</span>
            </Setting>
            {fit && (
              <Setting label="Target length">
                <span className={fit.within ? "text-green" : "text-amber"}>
                  {formatDuration(fit.target_s)} → {formatDuration(fit.achieved_s)}
                </span>{" "}
                <span className="text-ink-3">(natural {formatDuration(fit.natural_s)})</span>
              </Setting>
            )}
            <Setting label="Generated in">
              <span className="num">
                {take.stats.elapsed_s.toFixed(1)}s
                {take.stats.real_time_factor != null && ` · ${take.stats.real_time_factor.toFixed(2)}× real time`}
              </span>
            </Setting>
          </dl>
        </section>

        <section>
          <h3 className="mb-2 text-[14px] font-medium">Export</h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {EXPORT_CHOICES.map((item) => (
              <button
                key={item.label}
                type="button"
                disabled={!!exporting}
                onClick={() => exportAs(item.label, item.choice)}
                className="flex flex-col items-start gap-0.5 rounded-xl border border-rule-strong bg-panel px-3 py-2.5 text-left shadow-control transition-colors hover:bg-panel-2 disabled:opacity-50"
              >
                <span className="flex items-center gap-1.5 text-[13.5px] font-medium">
                  <Download className="size-3.5" /> {exporting === item.label ? "Exporting…" : item.label}
                </span>
                <span className="text-[12px] text-ink-3">{item.hint}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="mt-2 text-[12.5px] text-ink-3 underline-offset-2 hover:text-ink hover:underline"
            onClick={() => api.settings().then((st) => api.reveal(st.output_dir)).catch((e) => toastError(e))}
          >
            Open the output folder
          </button>
        </section>
      </div>
    </Dialog>
  );
}

/** Everything made in Text to Speech, newest first: listen, export the files, reuse or delete. */
export function Library() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["generations", "library", voiceId, q, page],
    queryFn: () => api.generations({ kind: "tts", voice_id: voiceId ?? undefined, q, limit: PAGE, offset: page * PAGE }),
  });

  async function remove(id: string) {
    try {
      await api.deleteGeneration(id);
      await queryClient.invalidateQueries({ queryKey: ["generations"] });
    } catch (err) {
      toastError(err, "Could not delete");
    }
  }

  return (
    <>
      <PageHeader
        title="Audio library"
        description="Everything you made in Text to Speech. Export any of it as WAV or MP3."
        actions={
          <Button asChild size="sm">
            <Link to="/generate">
              <AudioLines /> New speech
            </Link>
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="w-56">
          <VoicePicker value={voiceId} onChange={(id) => (setVoiceId(id), setPage(0))} includeDrafts />
        </div>
        {voiceId && (
          <Button variant="ghost" size="sm" onClick={() => setVoiceId(null)}>
            Any voice
          </Button>
        )}
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="absolute left-3 top-3.5 size-4 text-ink-3" />
          <Input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
            placeholder="Search the text"
            className="pl-9"
          />
        </div>
      </div>
      {isLoading ? (
        <Skeleton className="h-64" />
      ) : data?.items.length ? (
        <>
          <Card className="divide-y divide-rule">
            {data.items.map((g) => {
              const tone = g.params.tone;
              return (
                <div
                  key={g.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setOpenId(g.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpenId(g.id)}
                  className="flex cursor-pointer items-start gap-4 px-5 py-4 transition-colors hover:bg-panel-2/60"
                >
                  <div className="pt-0.5" onClick={(e) => e.stopPropagation()}>
                    <PlayButton id={g.id} url={api.generationAudioUrl(g.id)} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="selectable line-clamp-3 text-[14px] leading-relaxed">{g.text}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-ink-3">
                      <span className="font-medium text-ink-2">{g.voice_name}</span>
                      <span>· {languageLabel(g.language)}</span>
                      <span className="num">· {formatDuration(g.duration_s)}</span>
                      <span>· {formatDate(g.created_at)}</span>
                      {tone && <Badge tone="blue">Tone: {tone}</Badge>}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    <ExportMenu onExport={(c) => api.exportGeneration(g.id, c)} />
                    <Tooltip content="Open in Text to Speech">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label="Open in Text to Speech"
                        disabled={!g.voice_id}
                        onClick={() => navigate("/generate", { state: { text: g.text, voice_id: g.voice_id, language: g.language } })}
                      >
                        <Sparkles />
                      </Button>
                    </Tooltip>
                    <Tooltip content="Delete">
                      <Button size="icon-sm" variant="ghost" aria-label="Delete" onClick={() => void remove(g.id)}>
                        <Trash2 />
                      </Button>
                    </Tooltip>
                  </div>
                </div>
              );
            })}
          </Card>
          <div className="mt-4 flex items-center justify-between text-[13px] text-ink-2">
            <span className="num">
              {page * PAGE + 1}–{page * PAGE + data.items.length} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button variant="outline" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          icon={<LibraryIcon />}
          title={q || voiceId ? "Nothing matches" : "No speech yet"}
          action={
            <Button asChild size="sm">
              <Link to="/generate">Go to Text to Speech</Link>
            </Button>
          }
        >
          Everything you generate in Text to Speech is kept here.
        </EmptyState>
      )}
      {openId && data?.items.find((g) => g.id === openId) && (
        <TakeDialog
          take={data.items.find((g) => g.id === openId)!}
          onClose={() => setOpenId(null)}
          onDelete={() => {
            void remove(openId);
            setOpenId(null);
          }}
        />
      )}
    </>
  );
}
