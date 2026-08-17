// App shell: sidebar navigation over a tiny hash route (no router dependency). All six
// roadmap pages are implemented; an unknown hash falls back to the Summary landing page.

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { ForecastVsActualPage } from "@/pages/ForecastVsActualPage";
import { NextGwPage } from "@/pages/NextGwPage";
import { OptimizerAuditPage } from "@/pages/OptimizerAuditPage";
import { PlanBuilderPage } from "@/pages/PlanBuilderPage";
import { FixtureMatrixPage } from "@/pages/FixtureMatrixPage";
import { PlayersPage } from "@/pages/PlayersPage";
import { SummaryPage } from "@/pages/SummaryPage";

const DEFAULT_ROUTE = "summary";

const PAGES: Record<string, React.ComponentType> = {
  summary: SummaryPage,
  fixtures: FixtureMatrixPage,
  players: PlayersPage,
  "next-gw": NextGwPage,
  "plan-builder": PlanBuilderPage,
  "forecast-vs-actual": ForecastVsActualPage,
  optimizer: OptimizerAuditPage,
};

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
  const Page = PAGES[route] ?? SummaryPage;

  return (
    <div className="flex h-screen">
      <Sidebar active={route in PAGES ? route : DEFAULT_ROUTE} onNavigate={navigate} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end border-b px-4 py-2">
          <ThemeToggle />
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Page />
        </main>
      </div>
    </div>
  );
}
