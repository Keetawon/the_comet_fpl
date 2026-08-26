// App shell: sidebar navigation over a tiny hash route (no router dependency). An unknown
// hash falls back to the Summary landing page.

import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { NextGwPage } from "@/pages/NextGwPage";
import { OptimizerAuditPage } from "@/pages/OptimizerAuditPage";
import { PlanBuilderPage } from "@/pages/PlanBuilderPage";
import { PlayerAnalyticsPage } from "@/pages/PlayerAnalyticsPage";
import { PlayerForecastVsActualPage } from "@/pages/PlayerForecastVsActualPage";
import { FixtureMatrixPage } from "@/pages/FixtureMatrixPage";
import { PlayersPage } from "@/pages/PlayersPage";
import { SummaryPage } from "@/pages/SummaryPage";
import { TeamAnalyticsPage } from "@/pages/TeamAnalyticsPage";
import { TeamForecastVsActualPage } from "@/pages/TeamForecastVsActualPage";
import { UserDraftPage } from "@/pages/UserDraftPage";

const DEFAULT_ROUTE = "summary";

const PAGES: Record<string, React.ComponentType> = {
  summary: SummaryPage,
  fixtures: FixtureMatrixPage,
  "team-analytics": TeamAnalyticsPage,
  players: PlayersPage,
  "player-analytics": PlayerAnalyticsPage,
  "next-gw": NextGwPage,
  "plan-builder": PlanBuilderPage,
  "squad-draft": UserDraftPage,
  "player-forecast-vs-actual": PlayerForecastVsActualPage,
  "team-forecast-vs-actual": TeamForecastVsActualPage,
  // Temporary stable alias for bookmarks from schema v4.
  "forecast-vs-actual": PlayerForecastVsActualPage,
  optimizer: OptimizerAuditPage,
};

function routeFromHash(): string {
  const fragment = window.location.hash.slice(1);
  return fragment.split("?", 1)[0] || DEFAULT_ROUTE;
}

function useHashRoute(): [string, (id: string) => void] {
  const [route, setRoute] = useState(routeFromHash);
  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
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
