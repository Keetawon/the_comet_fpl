// App shell: sidebar navigation over a tiny hash route (no router dependency). Only the
// Fixture matrix page is implemented in P1.7b; the rest are labelled stubs.

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { FixtureMatrixPage } from "@/pages/FixtureMatrixPage";
import { PlayersPage } from "@/pages/PlayersPage";
import { StubPage } from "@/pages/StubPage";

const STUBS: Record<string, { phase: string; description: string }> = {
  summary: {
    phase: "later in P1.7",
    description: "Season snapshot: next deadline, latest run, headline EV and risk.",
  },
  "next-gw": {
    phase: "after GW1",
    description: "Next-gameweek squad suggestion: XI, captain, vice, bench, and EV deltas.",
  },
  "forecast-vs-actual": {
    phase: "after outcomes exist",
    description: "EV versus actual points, bias, calibration, and rank/capture by position.",
  },
  optimizer: {
    phase: "after GW1",
    description: "Optimizer run provenance, constraints, chosen squad, and transfer path.",
  },
};

function useHashRoute(): [string, (id: string) => void] {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || "fixtures");
  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash.slice(1) || "fixtures");
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  return [route, (id: string) => {
    window.location.hash = id;
    setRoute(id);
  }];
}

export default function App() {
  useEffect(() => initTheme(), []);
  const [route, navigate] = useHashRoute();
  const stub = STUBS[route];

  return (
    <div className="flex h-screen">
      <Sidebar active={route} onNavigate={navigate} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end border-b px-4 py-2">
          <ThemeToggle />
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          {route === "fixtures" ? (
            <FixtureMatrixPage />
          ) : route === "players" ? (
            <PlayersPage />
          ) : stub ? (
            <StubPage
              label={route === "summary" ? "Summary" : route.replace(/-/g, " ")}
              phase={stub.phase}
              description={stub.description}
            />
          ) : (
            <StubPage
              label="Fixture matrix"
              phase="redirect"
              description="Unknown page; use the sidebar."
            />
          )}
        </main>
      </div>
    </div>
  );
}
