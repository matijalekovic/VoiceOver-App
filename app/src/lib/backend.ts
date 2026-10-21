// How the UI finds the local API.
//
// In the desktop app the Rust shell starts the Python backend on a free port with a
// per-launch token and hands both over through the `backend_status` command. In a plain
// browser (UI development with `npm run dev`) they come from VITE_API_URL / VITE_API_TOKEN.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type BackendPhase = "installing" | "starting" | "ready" | "failed" | "stopped";

export interface BackendState {
  phase: BackendPhase;
  message: string;
  detail?: string | null;
  url?: string | null;
  token?: string | null;
  log?: string[];
}

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let connection: { url: string; token: string } | null = null;

export function setConnection(url: string, token: string) {
  connection = { url: url.replace(/\/$/, ""), token };
}

export function getConnection() {
  if (!connection) throw new Error("The backend is not connected yet.");
  return connection;
}

export async function readBackendState(): Promise<BackendState> {
  if (inTauri) return invoke<BackendState>("backend_status");
  const url = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8765";
  const token = import.meta.env.VITE_API_TOKEN ?? "dev-token";
  return { phase: "ready", message: "Development backend", url, token };
}

export async function onBackendState(handler: (state: BackendState) => void): Promise<UnlistenFn> {
  if (!inTauri) return () => {};
  return listen<BackendState>("backend://status", (event) => handler(event.payload));
}

export async function restartBackend(): Promise<void> {
  if (inTauri) await invoke("restart_backend");
}
