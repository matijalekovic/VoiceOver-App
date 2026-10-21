import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router";
import { Toaster } from "sonner";
import { BackendGate } from "@/components/backend-gate";
import { Layout } from "@/components/layout";
import { PlayerProvider } from "@/components/mini-player";
import { TooltipProvider } from "@/components/ui/misc";
import { useSettings } from "@/lib/hooks";
import { CloneVoice } from "@/pages/clone-voice";
import { Dashboard } from "@/pages/dashboard";
import { Generate } from "@/pages/generate";
import { History } from "@/pages/history";
import { ProjectEditor } from "@/pages/project-editor";
import { Projects } from "@/pages/projects";
import { Settings } from "@/pages/settings";
import { VoiceDetail } from "@/pages/voice-detail";
import { Voices } from "@/pages/voices";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 } },
});

// Hash routing: the bundled app is served from tauri://localhost without a server to rewrite paths.
const router = createHashRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/generate", element: <Generate /> },
      { path: "/voices", element: <Voices /> },
      { path: "/voices/:voiceId", element: <VoiceDetail /> },
      { path: "/clone", element: <CloneVoice /> },
      { path: "/projects", element: <Projects /> },
      { path: "/projects/:projectId", element: <ProjectEditor /> },
      { path: "/history", element: <History /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);

function ThemeSync() {
  const { data } = useSettings();
  useEffect(() => {
    const theme = data?.theme ?? "system";
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [data?.theme]);
  return null;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BackendGate>
          <ThemeSync />
          <PlayerProvider>
            <RouterProvider router={router} />
          </PlayerProvider>
        </BackendGate>
        <Toaster position="bottom-right" toastOptions={{ className: "!rounded-xl !text-[13.5px] !shadow-pop" }} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
