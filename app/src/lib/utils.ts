import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Language } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const total = Math.max(0, seconds);
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return m > 0 ? `${m}:${s.toFixed(0).padStart(2, "0")}` : `${s.toFixed(1)}s`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const LANGUAGE_LABELS: Record<string, string> = {
  english: "English",
  french: "French",
  spanish: "Spanish",
  german: "German",
  italian: "Italian",
  portuguese: "Portuguese",
  russian: "Russian",
  chinese: "Chinese",
  japanese: "Japanese",
  korean: "Korean",
};

export function languageLabel(code: string): string {
  return LANGUAGE_LABELS[code] ?? code;
}

export function enabledLanguages(languages: Language[] | undefined): Language[] {
  return (languages ?? []).filter((l) => l.enabled && l.supported_by_loaded_model !== false);
}

/** A stable hue per voice id, so each voice keeps the same orb colour. */
export function voiceHue(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return hash % 360;
}

export const SAMPLE_LINES: Record<string, string> = {
  english: "Hello, this is a short test of my cloned voice. How does it sound to you?",
  french: "Bonjour, ceci est un court essai de ma voix clonée. Qu'en pensez-vous ?",
  spanish: "Hola, esta es una breve prueba de mi voz clonada. ¿Qué te parece?",
  german: "Hallo, das ist ein kurzer Test meiner geklonten Stimme. Wie klingt sie?",
  italian: "Ciao, questa è una breve prova della mia voce clonata. Come ti sembra?",
  portuguese: "Olá, este é um breve teste da minha voz clonada. O que acha?",
};
