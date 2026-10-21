import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History as HistoryIcon, MoreHorizontal, Search, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { ExportMenu } from "@/components/export-menu";
import { PageHeader } from "@/components/layout";
import { PlayButton } from "@/components/mini-player";
import { VoicePicker } from "@/components/pickers";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
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
  Tabs,
} from "@/components/ui/misc";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";
import { formatDate, formatDuration, languageLabel } from "@/lib/utils";

const PAGE = 50;
const KIND_LABEL = { tts: "Generate", voice_test: "Voice test", segment: "Project" } as const;

export function History() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState("all");
  const [voiceId, setVoiceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["generations", "history", kind, voiceId, q, page],
    queryFn: () =>
      api.generations({ kind: kind === "all" ? undefined : kind, voice_id: voiceId ?? undefined, q, limit: PAGE, offset: page * PAGE }),
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
      <PageHeader title="History" description="Everything generated on this Mac, with the settings used." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs
          value={kind}
          onValueChange={(v) => {
            setKind(v);
            setPage(0);
          }}
          tabs={[
            { value: "all", label: "All" },
            { value: "tts", label: "Generate" },
            { value: "segment", label: "Projects" },
            { value: "voice_test", label: "Voice tests" },
          ]}
        />
        <div className="w-52">
          <VoicePicker value={voiceId} onChange={setVoiceId} includeDrafts />
        </div>
        {voiceId && (
          <Button variant="ghost" size="sm" onClick={() => setVoiceId(null)}>
            Any voice
          </Button>
        )}
        <div className="relative ml-auto w-64">
          <Search className="absolute left-3 top-2.5 size-4 text-ink-3" />
          <Input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
            placeholder="Search text"
            className="pl-9"
          />
        </div>
      </div>
      {isLoading ? (
        <Skeleton className="h-64" />
      ) : data?.items.length ? (
        <>
          <Card className="divide-y divide-rule">
            {data.items.map((g) => (
              <div key={g.id} className="flex items-center gap-4 px-4 py-3">
                <PlayButton id={g.id} url={api.generationAudioUrl(g.id)} />
                <div className="min-w-0 flex-1">
                  <p className="selectable line-clamp-2 text-[13.5px]">{g.text}</p>
                  <p className="mt-0.5 text-xs text-ink-3">
                    {g.voice_name} · {languageLabel(g.language)} · {g.model_id} · {formatDate(g.created_at)}
                    {g.stats.real_time_factor != null && ` · ${g.stats.elapsed_s.toFixed(1)}s to generate`}
                  </p>
                </div>
                <Badge>{KIND_LABEL[g.kind]}</Badge>
                <span className="num w-14 text-right text-xs text-ink-3">{formatDuration(g.duration_s)}</span>
                <ExportMenu onExport={(c) => api.exportGeneration(g.id, c)} label="" />
                <DropdownMenu>
                  <DropdownTrigger asChild>
                    <Button size="icon-sm" variant="ghost" aria-label="More">
                      <MoreHorizontal />
                    </Button>
                  </DropdownTrigger>
                  <DropdownContent>
                    <DropdownItem
                      onSelect={() => navigate("/generate", { state: { text: g.text, voice_id: g.voice_id, language: g.language } })}
                      disabled={!g.voice_id}
                    >
                      <Sparkles /> Open in Generate
                    </DropdownItem>
                    {g.project_id && (
                      <DropdownItem onSelect={() => navigate(`/projects/${g.project_id}`)}>Open project</DropdownItem>
                    )}
                    <DropdownSeparator />
                    <DropdownItem danger onSelect={() => void remove(g.id)}>
                      <Trash2 /> Delete
                    </DropdownItem>
                  </DropdownContent>
                </DropdownMenu>
              </div>
            ))}
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
        <EmptyState icon={<HistoryIcon />} title="Nothing here yet">
          Generated speech, voice tests and project takes are listed here.
        </EmptyState>
      )}
    </>
  );
}
