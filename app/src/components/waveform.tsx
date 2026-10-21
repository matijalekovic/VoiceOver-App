import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/plugins/regions";
import { cn, formatDuration } from "@/lib/utils";
import { Button } from "./ui/button";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

/**
 * Waveform player. With `region` set it also shows a draggable selection used for trimming.
 */
export function Waveform({
  url,
  height = 72,
  className,
  compact,
  region,
  onRegionChange,
  autoPlay,
}: {
  url: string | null;
  height?: number;
  className?: string;
  compact?: boolean;
  region?: { start: number; end: number };
  onRegionChange?: (start: number, end: number) => void;
  autoPlay?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regionRef = useRef<Region | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const onRegionChangeRef = useRef(onRegionChange);
  onRegionChangeRef.current = onRegionChange;
  const hasRegion = !!region;

  useEffect(() => {
    if (!container.current || !url) return;
    setError(null);
    const regions = hasRegion ? RegionsPlugin.create() : null;
    const instance = WaveSurfer.create({
      container: container.current,
      height,
      waveColor: cssVar("--wave"),
      progressColor: cssVar("--wave-progress"),
      cursorColor: cssVar("--ink-3"),
      cursorWidth: 1,
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
      normalize: true,
      url,
      plugins: regions ? [regions] : [],
    });
    ws.current = instance;
    instance.on("ready", (d) => {
      setDuration(d);
      if (regions && region) {
        regionRef.current = regions.addRegion({
          start: region.start,
          end: Math.min(region.end, d),
          color: "rgba(120, 140, 255, 0.14)",
          drag: true,
          resize: true,
        });
      }
      if (autoPlay) instance.play();
    });
    instance.on("timeupdate", (t) => setTime(t));
    instance.on("play", () => setPlaying(true));
    instance.on("pause", () => setPlaying(false));
    instance.on("finish", () => setPlaying(false));
    instance.on("error", (e) => setError(String(e)));
    regions?.on("region-updated", (r) => onRegionChangeRef.current?.(r.start, r.end));
    regions?.on("region-clicked", (r, e) => {
      e.stopPropagation();
      r.play();
    });
    return () => {
      instance.destroy();
      ws.current = null;
      regionRef.current = null;
    };
    // The region's initial bounds are read once per URL; later edits come from the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, height, hasRegion]);

  useEffect(() => {
    const r = regionRef.current;
    if (r && region && (Math.abs(r.start - region.start) > 0.01 || Math.abs(r.end - region.end) > 0.01)) {
      r.setOptions({ start: region.start, end: region.end });
    }
  }, [region]);

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <Button
        variant={compact ? "secondary" : "primary"}
        size={compact ? "icon-sm" : "icon"}
        aria-label={playing ? "Pause" : "Play"}
        disabled={!url || !!error}
        onClick={() => ws.current?.playPause()}
      >
        {playing ? <Pause /> : <Play className="translate-x-px" />}
      </Button>
      <div className="min-w-0 flex-1">
        {error ? (
          <p className="text-[13px] text-red">The audio could not be loaded.</p>
        ) : (
          <div ref={container} className="w-full cursor-pointer" />
        )}
      </div>
      <span className="num w-20 shrink-0 text-right text-xs text-ink-3">
        {formatDuration(time)} / {formatDuration(duration)}
      </span>
    </div>
  );
}
