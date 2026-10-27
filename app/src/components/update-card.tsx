import { relaunch } from "@tauri-apps/plugin-process";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { inTauri } from "@/lib/backend";
import { toastError, useActiveJobs } from "@/lib/hooks";
import { Button } from "./ui/button";

// Checked at launch and then every few hours; releases are published from version tags.
const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;

/** A newer version of the app, from the project's GitHub Releases, signed with its key. */
export function UpdateCard() {
  const [update, setUpdate] = useState<Update | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number | null } | null>(null);
  const { data: jobs } = useActiveJobs();
  const busy = (jobs?.length ?? 0) > 0;

  useEffect(() => {
    if (!inTauri) return;
    let cancelled = false;
    const look = () =>
      check()
        .then((found) => !cancelled && setUpdate(found))
        .catch(() => {}); // offline, or no release yet: try again later
    void look();
    const timer = window.setInterval(look, CHECK_EVERY_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!update) return null;

  async function install() {
    if (!update) return;
    setProgress({ done: 0, total: null });
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") setProgress({ done: 0, total: event.data.contentLength ?? null });
        if (event.event === "Progress") setProgress((p) => p && { ...p, done: p.done + event.data.chunkLength });
      });
      await relaunch();
    } catch (err) {
      setProgress(null);
      toastError(err, "Could not install the update");
    }
  }

  const percent = progress?.total ? Math.round((progress.done / progress.total) * 100) : null;
  return (
    <div className="rounded-xl border border-rule bg-panel-2 px-3 py-2.5">
      <p className="text-[13px] font-medium">Version {update.version} is available</p>
      <p className="mt-0.5 text-[11.5px] text-ink-3">
        {busy ? "Install it when the current generation finishes." : "Installs and restarts the app."}
      </p>
      <Button size="sm" className="mt-2 w-full" onClick={install} disabled={busy} loading={!!progress}>
        <Download /> {progress ? (percent !== null ? `Downloading ${percent}%` : "Installing…") : "Install update"}
      </Button>
    </div>
  );
}
