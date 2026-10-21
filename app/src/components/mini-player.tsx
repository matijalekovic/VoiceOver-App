import { Pause, Play } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";

// One shared <audio> element for lists (history, segments, voice cards), so starting one
// clip stops the previous one and long lists do not each build a waveform.

interface PlayerState {
  currentId: string | null;
  playing: boolean;
  toggle: (id: string, url: string) => void;
  stop: () => void;
}

const PlayerContext = createContext<PlayerState | null>(null);

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const el = new Audio();
    el.addEventListener("play", () => setPlaying(true));
    el.addEventListener("pause", () => setPlaying(false));
    el.addEventListener("ended", () => setPlaying(false));
    audio.current = el;
    return () => el.pause();
  }, []);

  const toggle = useCallback(
    (id: string, url: string) => {
      const el = audio.current;
      if (!el) return;
      if (currentId === id) {
        if (el.paused) void el.play();
        else el.pause();
        return;
      }
      el.src = url;
      setCurrentId(id);
      void el.play();
    },
    [currentId],
  );

  const stop = useCallback(() => {
    audio.current?.pause();
  }, []);

  return <PlayerContext.Provider value={{ currentId, playing, toggle, stop }}>{children}</PlayerContext.Provider>;
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer outside PlayerProvider");
  return ctx;
}

export function PlayButton({
  id,
  url,
  size = "icon-sm",
  variant = "secondary",
  label,
}: {
  id: string;
  url: string | null;
  size?: "icon-sm" | "icon";
  variant?: "secondary" | "primary" | "ghost";
  label?: string;
}) {
  const player = usePlayer();
  const active = player.currentId === id && player.playing;
  return (
    <Button
      size={size}
      variant={variant}
      disabled={!url}
      aria-label={active ? "Pause" : (label ?? "Play")}
      onClick={(e) => {
        e.stopPropagation();
        if (url) player.toggle(id, url);
      }}
    >
      {active ? <Pause /> : <Play className="translate-x-px" />}
    </Button>
  );
}
