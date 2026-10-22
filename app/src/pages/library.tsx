import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Library as LibraryIcon, Search, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { VoicePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { Badge, Card, EmptyState, Skeleton, Tooltip } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

const PAGE = 30;

/** Everything made in Text to Speech, newest first: listen, export the files, reuse or delete. */
export function Library() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
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
                <div key={g.id} className="flex items-start gap-4 px-5 py-4">
                  <div className="pt-0.5">
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
                  <div className="flex shrink-0 items-center gap-1">
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
    </>
  );
}
