// App shell: sidebar navigation over a tiny hash route (no router dependency). Only the
// Fixture matrix page is implemented in P1.7b; the rest are labelled stubs.

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { ForecastVsActualPage } from "@/pages/ForecastVsActualPage";
import { NextGwPage } from "@/pages/NextGwPage";
import { FixtureMatrixPage } from "@/pages/FixtureMatrixPage";
import { PlayersPage } from "@/pages/PlayersPage";
import { StubPage } from "@/pages/StubPage";
import { SummaryPage } from "@/pages/SummaryPage";

const STUBS: Record<string, { phase: string; description: string }> = {
  optimizer: {
    phase: "after GW1",
    description: "Optimizer run provenance, constraints, chosen squad, and transfer path.",
  },
};

const DEFAULT_ROUTE = "summary";

function useHashRoute(): [string, (id: string) => void] {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || DEFAULT_ROUTE);
  useEffect(() => {
    const onHashChange = () => setRoute(window.location.hash.slice(1) || DEFAULT_ROUTE);
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
          {route === "summary" ? (
            <SummaryPage />
          ) : route === "fixtures" ? (
            <FixtureMatrixPage />
          ) : route === "players" ? (
            <PlayersPage />
          ) : route === "next-gw" ? (
            <NextGwPage />
          ) : route === "forecast-vs-actual" ? (
            <ForecastVsActualPage />
          ) : stub ? (
            <StubPage label={route.replace(/-/g, " ")} phase={stub.phase} description={stub.description} />
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
