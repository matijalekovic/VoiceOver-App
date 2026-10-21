import { Download, FolderOpen } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { toastError } from "@/lib/hooks";
import type { ExportResult } from "@/lib/types";
import { Button } from "./ui/button";
import { DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "./ui/misc";

export type ExportChoice = { format: "wav" | "mp3"; bitrate?: 192 | 320; sample_rate?: number | null };

const CHOICES: { label: string; hint: string; choice: ExportChoice }[] = [
  { label: "WAV", hint: "Lossless · 24 kHz", choice: { format: "wav" } },
  { label: "WAV 48 kHz", hint: "Lossless · for video", choice: { format: "wav", sample_rate: 48000 } },
  { label: "MP3 320 kbps", hint: "High quality", choice: { format: "mp3", bitrate: 320 } },
  { label: "MP3 192 kbps", hint: "Smaller file", choice: { format: "mp3", bitrate: 192 } },
];

export function announceExport(result: ExportResult) {
  const first = result.paths[0];
  const name = first?.split("/").pop();
  toast.success(result.paths.length > 1 ? `Exported ${result.paths.length} files` : `Exported ${name}`, {
    description: result.folder,
    action: first
      ? { label: "Show in Finder", onClick: () => api.reveal(first).catch((e) => toastError(e, "Could not open Finder")) }
      : undefined,
  });
}

export function ExportMenu({
  onExport,
  disabled,
  label = "Export",
  size = "sm",
}: {
  onExport: (choice: ExportChoice) => Promise<ExportResult>;
  disabled?: boolean;
  label?: string;
  size?: "sm" | "md";
}) {
  const [busy, setBusy] = useState(false);
  async function run(choice: ExportChoice) {
    setBusy(true);
    try {
      announceExport(await onExport(choice));
    } catch (err) {
      toastError(err, "Export failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <DropdownMenu>
      <DropdownTrigger asChild>
        <Button variant="outline" size={size} disabled={disabled} loading={busy}>
          <Download /> {label}
        </Button>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Save to the output folder</DropdownLabel>
        {CHOICES.map((item) => (
          <DropdownItem key={item.label} onSelect={() => run(item.choice)}>
            <span className="flex-1">{item.label}</span>
            <span className="text-xs text-ink-3">{item.hint}</span>
          </DropdownItem>
        ))}
        <DropdownSeparator />
        <DropdownItem onSelect={() => api.settings().then((s) => api.reveal(s.output_dir)).catch((e) => toastError(e))}>
          <FolderOpen /> Open output folder
        </DropdownItem>
      </DropdownContent>
    </DropdownMenu>
  );
}
