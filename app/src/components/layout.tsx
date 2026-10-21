import {
  AudioLines,
  ChevronRight,
  FolderKanban,
  History as HistoryIcon,
  House,
  Mic,
  Settings as SettingsIcon,
  UsersRound,
} from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useActiveJobs, useModels, useStatus } from "@/lib/hooks";
import { cn, formatBytes } from "@/lib/utils";
import { BrandMark } from "./brand";
import { stageLabel } from "./job-progress";

const NAV_GROUPS = [
  {
    items: [
      { to: "/", label: "Home", icon: House, end: true },
      { to: "/voices", label: "Voices", icon: UsersRound },
      { to: "/projects", label: "Projects", icon: FolderKanban },
    ],
  },
  {
    title: "Create",
    items: [
      { to: "/generate", label: "Text to Speech", icon: AudioLines },
      { to: "/clone", label: "Voice Cloning", icon: Mic },
      { to: "/history", label: "History", icon: HistoryIcon },
    ],
  },
];

const SECTIONS: Record<string, string> = {
  "": "Home",
  generate: "Text to Speech",
  voices: "Voices",
  clone: "Voice Cloning",
  projects: "Projects",
  history: "History",
  settings: "Settings",
};
const DETAIL: Record<string, string> = { voices: "Voice", projects: "Project" };

function Breadcrumb() {
  const [section = "", detail] = useLocation().pathname.split("/").filter(Boolean);
  const label = SECTIONS[section] ?? section;
  return (
    <nav className="flex min-w-0 items-center gap-2 text-[14.5px]" aria-label="Breadcrumb">
      {detail ? (
        <>
          <Link to={`/${section}`} className="text-ink-3 transition-colors hover:text-ink">
            {label}
          </Link>
          <ChevronRight className="size-4 shrink-0 text-ink-3" />
          <span className="truncate font-medium">{DETAIL[section] ?? detail}</span>
        </>
      ) : (
        <span className="font-medium">{label}</span>
      )}
    </nav>
  );
}

function SideLink({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof House; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex h-9 items-center gap-3 rounded-[10px] px-2.5 text-[14.5px] text-ink transition-colors",
          isActive ? "bg-panel-2 font-medium" : "hover:bg-panel-2/70",
        )
      }
    >
      <Icon className="size-[18px] text-ink-2" strokeWidth={1.75} />
      {label}
    </NavLink>
  );
}

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
    <div className="rounded-2xl border border-rule bg-panel px-3.5 py-3 text-xs shadow-card">
      <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
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
      <aside className="flex w-[244px] shrink-0 flex-col border-r border-rule bg-panel px-3 pb-3">
        {/* Space for the macOS traffic lights; the strip drags the window. */}
        <div className="h-10 shrink-0" data-tauri-drag-region />
        <Link to="/" className="mb-6 flex items-center gap-2 px-2.5">
          <BrandMark size={22} />
          <span className="text-[18px] font-bold tracking-[-0.02em]">Voice Studio</span>
        </Link>
        <nav className="flex flex-col gap-6">
          {NAV_GROUPS.map((group, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              {group.title && <p className="mb-1 px-2.5 text-[13.5px] text-ink-3">{group.title}</p>}
              {group.items.map((item) => (
                <SideLink key={item.to} {...item} />
              ))}
            </div>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-3">
          <SideLink to="/settings" label="Settings" icon={SettingsIcon} />
          <EngineCard />
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex h-[60px] shrink-0 items-center gap-4 border-b border-rule bg-panel px-8"
          data-tauri-drag-region
        >
          <Breadcrumb />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-10 pb-16 pt-9">
            <Outlet />
          </div>
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
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[30px] font-medium leading-tight tracking-[-0.02em]">{title}</h1>
        {description && <p className="mt-1.5 text-[14.5px] text-ink-3">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
