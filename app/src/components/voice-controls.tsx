import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { Slider as SliderPrimitive } from "radix-ui";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";
import type { Style, Voice } from "@/lib/types";
import { cn, languageLabel } from "@/lib/utils";
import { Button } from "./ui/button";
import { Input, Label } from "./ui/form";
import { Select } from "./ui/select";

/** What a generation asks for: a style take of the voice (null = its chosen clip) and delivery. */
export interface Delivery {
  clipId: string | null;
  style: Style;
  /** A tone instruction such as "cheerful" (empty for none). Not saved with the voice. */
  tone: string;
}

const TONES = ["Cheerful", "Calm", "Serious", "Excited", "Warm"];

export function languageProfile(voice: Voice | undefined | null, language: string | null | undefined) {
  if (!voice || !language) return undefined;
  return voice.languages.find((l) => l.language === language.toLowerCase());
}

/** The delivery a generation starts from: the voice's own, then its language profile's. */
export function deliveryFor(voice: Voice | undefined | null, language?: string | null): Delivery {
  return {
    clipId: null,
    style: {
      ...(voice?.style ?? { expressiveness: 0.6, speed: 1, pitch: 0 }),
      ...(languageProfile(voice, language)?.style ?? {}),
    },
    tone: "",
  };
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  ends,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  ends: [string, string];
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label>{label}</Label>
        <span className="num text-[13px] text-ink-2">{format(value)}</span>
      </div>
      <SliderPrimitive.Root
        className="relative flex h-5 w-full touch-none select-none items-center"
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
        aria-label={label}
      >
        <SliderPrimitive.Track className="relative h-1.5 grow rounded-full bg-panel-3">
          <SliderPrimitive.Range className="absolute h-full rounded-full bg-accent" />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb className="block size-4 rounded-full border border-rule-strong bg-panel shadow-control outline-none focus-visible:ring-4 focus-visible:ring-panel-3" />
      </SliderPrimitive.Root>
      <div className="flex justify-between text-[11.5px] text-ink-3">
        <span>{ends[0]}</span>
        <span>{ends[1]}</span>
      </div>
      {hint && <p className="text-[11.5px] text-ink-3">{hint}</p>}
    </div>
  );
}

const sameStyle = (a: Style, b: Style) =>
  Math.abs(a.expressiveness - b.expressiveness) < 0.005 && Math.abs(a.speed - b.speed) < 0.005 && Math.abs(a.pitch - b.pitch) < 0.05;

/**
 * Style take plus expressiveness, speed and pitch for one generation, with a way to make the
 * current settings the voice's defaults (projects use those).
 */
export function VoiceControls({
  voice,
  value,
  onChange,
  language,
  className,
}: {
  voice: Voice;
  value: Delivery;
  onChange: (value: Delivery) => void;
  /** The language being generated, to explain how a cloned voice will speak it. */
  language?: string | null;
  className?: string;
}) {
  const cloned = voice.mode !== "design";
  const otherLanguage = cloned && !!language && language.toLowerCase() !== voice.language.toLowerCase();
  const profile = otherLanguage ? languageProfile(voice, language) : undefined;
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<Style>) => onChange({ ...value, style: { ...value.style, ...patch } });
  const takes = voice.clips.filter((c) => c.kept && c.id !== voice.clip_id);
  const defaults = deliveryFor(voice, language).style;
  const isDefault = sameStyle(value.style, defaults);

  async function saveDefault() {
    setSaving(true);
    try {
      if (profile) {
        // Saved for this language only: what differs from the voice's own delivery.
        const overrides = Object.fromEntries(
          (Object.keys(value.style) as (keyof Style)[])
            .filter((k) => Math.abs(value.style[k] - voice.style[k]) > 0.001)
            .map((k) => [k, value.style[k]]),
        );
        await api.updateLanguage(voice.id, profile.language, { style: overrides });
      } else {
        await api.updateVoice(voice.id, { style: value.style });
      }
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
      await queryClient.invalidateQueries({ queryKey: ["voice", voice.id] });
      toast.success(
        profile
          ? `Saved as ${voice.name}'s ${languageLabel(profile.language)} delivery`
          : `Saved as ${voice.name}'s default delivery`,
      );
    } catch (err) {
      toastError(err, "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={cn("space-y-4", className)}>
      {otherLanguage && (
        <p className="rounded-xl bg-blue-soft px-3 py-2 text-[12.5px] text-blue">
          {voice.name} was recorded in {languageLabel(voice.language)}.{" "}
          {!profile
            ? `In ${languageLabel(language!)} it speaks from its voice fingerprint, with native pronunciation. Add ${languageLabel(language!)} under Languages on the voice's page to keep it steadier from paragraph to paragraph.`
            : profile.accent === "carried"
              ? `In ${languageLabel(language!)} it continues the original recording, keeping ${voice.name}'s own accent.`
              : `In ${languageLabel(language!)} it continues the chosen ${languageLabel(language!)} take, with native pronunciation, so every paragraph keeps the same delivery.`}
        </p>
      )}
      <div className="space-y-2">
        <Label htmlFor="tone">Tone</Label>
        <Input
          id="tone"
          value={value.tone}
          onChange={(e) => onChange({ ...value, tone: e.target.value.slice(0, 300) })}
          placeholder="Optional, e.g. cheerful and upbeat"
          className="h-9 text-[13.5px]"
        />
        <div className="flex flex-wrap gap-1.5">
          {TONES.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onChange({ ...value, tone: value.tone === t ? "" : t })}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[12px] transition-colors",
                value.tone === t ? "border-ink bg-accent text-accent-ink" : "border-rule-strong text-ink-2 hover:bg-panel-2",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        {cloned && value.tone.trim() && (
          <p className="text-[11.5px] text-ink-3">
            A tone makes the voice speak from its fingerprint, which follows instructions but keeps a little less of the
            original recording's character.
          </p>
        )}
      </div>
      {takes.length > 0 && (
        <div className="space-y-2">
          <Label>Style</Label>
          <Select
            size="sm"
            value={value.clipId ?? "default"}
            onValueChange={(id) => onChange({ ...value, clipId: id === "default" ? null : id })}
            options={[
              { value: "default", label: "Default", description: "The take saved with the voice" },
              ...takes.map((c) => ({ value: c.id, label: c.name || "Kept take", description: `“${c.transcript.slice(0, 60)}…”` })),
            ]}
          />
        </div>
      )}
      <Slider
        label="Expressiveness"
        value={value.style.expressiveness}
        min={0}
        max={1}
        step={0.05}
        format={(v) => `${Math.round(v * 100)}%`}
        ends={["Steady", "Varied"]}
        hint="Lower reads calmer and flatter. Above the middle, each take varies more; for more energy, keep an energetic take as a Style."
        onChange={(expressiveness) => set({ expressiveness })}
      />
      <Slider
        label="Speed"
        value={value.style.speed}
        min={0.8}
        max={1.25}
        step={0.05}
        format={(v) => `${v.toFixed(2)}×`}
        ends={["Slower", "Faster"]}
        onChange={(speed) => set({ speed })}
      />
      <Slider
        label="Pitch"
        value={value.style.pitch}
        min={-2}
        max={2}
        step={0.5}
        format={(v) => (v === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v)} st`)}
        ends={["Lower", "Higher"]}
        onChange={(pitch) => set({ pitch })}
      />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={saveDefault} loading={saving} disabled={isDefault}>
          {profile ? `Save as ${languageLabel(profile.language)} default` : "Save as voice default"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onChange(deliveryFor(voice, language))}
          disabled={isDefault && !value.clipId && !value.tone}
        >
          <RotateCcw /> Reset
        </Button>
      </div>
    </div>
  );
}
