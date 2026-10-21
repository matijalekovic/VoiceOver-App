import {
  AudioLines,
  FolderKanban,
  History as HistoryIcon,
  LayoutGrid,
  Mic2,
  Settings as SettingsIcon,
  UserRound,
} from "lucide-react";
import { NavLink, Outlet } from "react-router";
import { useActiveJobs, useModels, useStatus } from "@/lib/hooks";
import { cn, formatBytes } from "@/lib/utils";
import { BrandMark } from "./brand";
import { stageLabel } from "./job-progress";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutGrid, end: true },
  { to: "/generate", label: "Generate", icon: AudioLines },
  { to: "/voices", label: "My Voices", icon: UserRound, end: true },
  { to: "/clone", label: "Clone Voice", icon: Mic2 },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/history", label: "History", icon: HistoryIcon },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function EngineCard() {
  const { data: status } = useStatus();
  const { data: models } = useModels();
  const { data: jobs } = useActiveJobs();
  const engine = status?.engine;
  const model = models?.find((m) => m.id === engine?.loaded_model_id);
  const running = jobs?.find((j) => !["queued"].includes(j.status));
  const queued = jobs?.filter((j) => j.status === "queued").length ?? 0;
  const dot =
    engine?.state === "busy" || running
      ? "bg-blue animate-pulse"
      : engine?.state === "ready"
        ? "bg-green"
        : engine?.state === "loading"
          ? "bg-amber animate-pulse"
          : "bg-ink-3";
  return (
    <div className="rounded-xl border border-rule bg-panel px-3 py-2.5 text-xs">
      <div className="flex items-center gap-2 font-medium text-ink">
        <span className={cn("size-2 rounded-full", dot)} />
        {running ? stageLabel(running) : model ? `${model.parameters} ${model.quantization} loaded` : "No model loaded"}
      </div>
      <div className="mt-1 flex justify-between text-ink-3">
        <span>{queued ? `${queued} queued` : engine?.state === "ready" ? "Ready" : "Idle"}</span>
        {status && <span className="num">{formatBytes(status.memory.available_bytes)} free</span>}
      </div>
    </div>
  );
}

export function Layout() {
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-rule bg-panel-2/40 px-3 pb-3">
        {/* Space for the macOS traffic lights; the strip drags the window. */}
        <div className="h-10 shrink-0" data-tauri-drag-region />
        <div className="mb-5 flex items-center gap-2.5 px-2" data-tauri-drag-region>
          <BrandMark size={26} />
          <div className="leading-tight">
            <p className="text-[13px] font-semibold">Voice Studio</p>
            <p className="text-[11px] text-ink-3">1PAX · local</p>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors",
                  isActive ? "bg-panel-3 font-medium text-ink" : "text-ink-2 hover:bg-panel-2 hover:text-ink",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <EngineCard />
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="h-10" data-tauri-drag-region />
        <div className="mx-auto max-w-6xl px-8 pb-16">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[13.5px] text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
