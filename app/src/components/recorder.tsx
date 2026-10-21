import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RecordPlugin from "wavesurfer.js/plugins/record";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";

/** Records from the microphone with a live waveform; hands back the finished recording. */
export function Recorder({ onRecorded, className }: { onRecorded: (blob: Blob, filename: string) => void; className?: string }) {
  const container = useRef<HTMLDivElement>(null);
  const record = useRef<RecordPlugin | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const onRecordedRef = useRef(onRecorded);
  onRecordedRef.current = onRecorded;

  useEffect(() => {
    if (!container.current) return;
    const ws = WaveSurfer.create({
      container: container.current,
      height: 56,
      waveColor: getComputedStyle(document.documentElement).getPropertyValue("--ink").trim(),
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
    });
    const plugin = ws.registerPlugin(RecordPlugin.create({ scrollingWaveform: true, renderRecordedAudio: false }));
    plugin.on("record-progress", (ms) => setSeconds(ms / 1000));
    plugin.on("record-end", (blob) => {
      setRecording(false);
      const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
      onRecordedRef.current(blob, `recording-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.${ext}`);
    });
    record.current = plugin;
    return () => ws.destroy();
  }, []);

  async function toggle() {
    const plugin = record.current;
    if (!plugin) return;
    setError(null);
    if (plugin.isRecording()) {
      plugin.stopRecording();
      return;
    }
    try {
      setSeconds(0);
      await plugin.startRecording({ echoCancellation: false, noiseSuppression: false, autoGainControl: false });
      setRecording(true);
    } catch (err) {
      setError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone access was refused. Allow it in System Settings → Privacy & Security → Microphone."
          : `Could not start recording: ${String(err)}`,
      );
    }
  }

  return (
    <div className={cn("rounded-xl border border-rule bg-panel-2/50 p-3", className)}>
      <div className="flex items-center gap-3">
        <Button variant={recording ? "danger" : "primary"} size="icon" onClick={toggle} aria-label={recording ? "Stop recording" : "Record"}>
          {recording ? <Square /> : <Mic />}
        </Button>
        <div ref={container} className="min-w-0 flex-1" />
        <span className={cn("num w-14 text-right text-sm", seconds > 30 ? "text-amber" : "text-ink-2")}>{seconds.toFixed(1)}s</span>
      </div>
      <p className="mt-2 text-xs text-ink-3">
        {recording ? "Recording… read naturally, then press stop." : "Record 10–30 seconds in a quiet room, about a hand's width from the microphone."}
      </p>
      {error && <p className="mt-1 text-xs text-red">{error}</p>}
    </div>
  );
}
