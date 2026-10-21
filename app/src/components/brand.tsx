import type * as React from "react";
import { cn, voiceHue } from "@/lib/utils";

/** The 1PAX mark as an app tile: paper on ink, inverting with the theme. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path d="M8 22V10h3.2l4.8 7.4V10H19v12h-3.1L11 14.5V22z" fill="var(--accent-ink)" />
      <rect x="21" y="18.5" width="3.5" height="3.5" rx="0.6" fill="var(--accent-ink)" />
    </svg>
  );
}

/** The soft gradient orb. With a voice id it takes that voice's colour. */
export function Orb({
  size = 96,
  voiceId,
  still,
  className,
}: {
  size?: number;
  voiceId?: string;
  still?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn("orb", className)}
      style={
        {
          width: size,
          height: size,
          "--orb-size": `${size}px`,
          "--orb-hue": voiceId ? `${voiceHue(voiceId)}deg` : "0deg",
          "--orb-play": still ? "paused" : "running",
        } as React.CSSProperties
      }
    />
  );
}
