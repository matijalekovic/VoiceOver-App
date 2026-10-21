import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { type BackendState, onBackendState, readBackendState, restartBackend, setConnection } from "@/lib/backend";
import { BrandMark, Orb } from "./brand";
import { Button } from "./ui/button";
import { Progress } from "./ui/misc";

/**
 * Holds the UI back until the local engine answers. On the very first launch this is where
 * the Python runtime is installed (the shell streams its progress here).
 */
export function BackendGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<BackendState>({ phase: "starting", message: "Starting the engine…" });
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    const apply = (next: BackendState) => {
      if (cancelled) return;
      setState(next);
      if (next.phase === "ready" && next.url && next.token) {
        setConnection(next.url, next.token);
        setConnected(true);
        void queryClient.invalidateQueries();
      } else if (next.phase !== "ready") {
        setConnected(false);
      }
    };
    void onBackendState(apply).then((fn) => {
      unlisten = fn;
    });
    void readBackendState().then(apply);
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [queryClient]);

  if (connected) return <>{children}</>;

  const failed = state.phase === "failed" || state.phase === "stopped";
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 px-8" data-tauri-drag-region>
      <div className="relative">
        <Orb size={120} still={failed} />
        <div className="absolute inset-0 flex items-center justify-center">
          <BrandMark size={34} />
        </div>
      </div>
      <div className="max-w-lg text-center">
        <h1 className="text-xl font-semibold">{state.phase === "installing" ? "Setting up Voice Studio" : "1PAX Voice Studio"}</h1>
        <p className="mt-1 text-[13px] text-ink-2">{state.message}</p>
        {state.phase === "installing" && (
          <p className="mt-1 text-xs text-ink-3">
            First launch only: installing the local runtime. This needs an internet connection and takes a few minutes.
          </p>
        )}
      </div>
      {!failed && <Progress value={null} className="w-72" />}
      {failed && (
        <div className="w-full max-w-xl space-y-3">
          <div className="flex items-start gap-2 rounded-xl bg-red-soft px-4 py-3 text-[13px] text-red">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <p className="selectable">{state.detail ?? "The engine stopped."}</p>
          </div>
          <div className="flex justify-center">
            <Button onClick={() => void restartBackend()}>
              <RotateCcw /> Try again
            </Button>
          </div>
        </div>
      )}
      {state.log && state.log.length > 0 && (
        <pre className="selectable max-h-48 w-full max-w-2xl overflow-auto rounded-xl bg-panel-2 p-3 text-[11px] leading-relaxed text-ink-2">
          {state.log.slice(-40).join("\n")}
        </pre>
      )}
    </div>
  );
}
