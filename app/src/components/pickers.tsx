import { useLanguages, useModels, useVoices } from "@/lib/hooks";
import { enabledLanguages, languageLabel } from "@/lib/utils";
import { Select } from "./ui/select";

export function VoicePicker({
  value,
  onChange,
  includeDrafts = false,
  className,
  id,
}: {
  value: string | null | undefined;
  onChange: (id: string) => void;
  includeDrafts?: boolean;
  className?: string;
  id?: string;
}) {
  const { data: voices } = useVoices();
  const options = (voices ?? [])
    .filter((v) => includeDrafts || v.status === "ready")
    .map((v) => ({
      value: v.id,
      label: v.name,
      description: `${languageLabel(v.language)}${v.status === "draft" ? " · draft" : ""}`,
    }));
  return (
    <Select
      id={id}
      className={className}
      value={value ?? undefined}
      onValueChange={onChange}
      options={options}
      placeholder={options.length ? "Choose a voice" : "No voices yet"}
      disabled={!options.length}
    />
  );
}

export function LanguagePicker({
  value,
  onChange,
  className,
  id,
  size,
}: {
  value: string | null | undefined;
  onChange: (code: string) => void;
  className?: string;
  id?: string;
  size?: "sm" | "md";
}) {
  const { data } = useLanguages();
  const options = enabledLanguages(data).map((l) => ({
    value: l.code,
    label: l.label,
    description: l.evaluation.status === "verified" ? "Verified" : undefined,
  }));
  // Keep a value that was chosen earlier visible even if it has since been disabled.
  if (value && !options.some((o) => o.value === value)) {
    options.push({ value, label: languageLabel(value), description: "Not enabled in Settings" });
  }
  return <Select id={id} size={size} className={className} value={value ?? undefined} onValueChange={onChange} options={options} />;
}

export function ModelPicker({
  value,
  onChange,
  className,
  id,
  size,
}: {
  value: string | null | undefined;
  onChange: (id: string) => void;
  className?: string;
  id?: string;
  size?: "sm" | "md";
}) {
  const { data } = useModels();
  const options = (data ?? []).map((m) => ({
    value: m.id,
    label: `${m.tier === "quality" ? "Quality" : "Lightweight"} · ${m.parameters}${m.quantization !== "bf16" ? ` ${m.quantization}` : ""}`,
    description:
      m.status.state === "installed" ? (m.loaded ? "Loaded" : "Installed") : "Not installed — see Settings → Models",
    disabled: m.status.state !== "installed",
  }));
  return <Select id={id} size={size} className={className} value={value ?? undefined} onValueChange={onChange} options={options} />;
}
