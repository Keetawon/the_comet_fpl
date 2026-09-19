// App shell: sidebar navigation over a tiny hash route (no router dependency). An unknown
// hash falls back to the Summary landing page.

import { lazy, Suspense, useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { PageBoundary } from "@/components/PageBoundary";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { isPageAvailable } from "@/lib/pageAccess";

const SummaryPage = lazy(() => import("@/pages/SummaryPage").then(m => ({ default: m.SummaryPage })));
const PlayerForecastVsActualPage = lazy(() => import("@/pages/PlayerForecastVsActualPage").then(m => ({ default: m.PlayerForecastVsActualPage })));

const DEFAULT_ROUTE = "summary";

const PAGES: Record<string, React.ComponentType> = {
  summary: SummaryPage,
  news: lazy(() => import("@/pages/NewsPage").then(m => ({ default: m.NewsPage }))),
  "gw-analysis": lazy(() => import("@/pages/GwAnalysisPage").then(m => ({ default: m.GwAnalysisPage }))),
  fixtures: lazy(() => import("@/pages/FixtureMatrixPage").then(m => ({ default: m.FixtureMatrixPage }))),
  "team-analytics": lazy(() => import("@/pages/TeamAnalyticsPage").then(m => ({ default: m.TeamAnalyticsPage }))),
  "team-stat-sdp": lazy(() => import("@/pages/SdpStatsPage").then(m => ({ default: m.TeamSdpStatsPage }))),
  players: lazy(() => import("@/pages/PlayersPage").then(m => ({ default: m.PlayersPage }))),
  "player-analytics": lazy(() => import("@/pages/PlayerAnalyticsPage").then(m => ({ default: m.PlayerAnalyticsPage }))),
  "next-gw": lazy(() => import("@/pages/NextGwPage").then(m => ({ default: m.NextGwPage }))),
  "plan-builder": lazy(() => import("@/pages/PlanBuilderPage").then(m => ({ default: m.PlanBuilderPage }))),
  "squad-draft": lazy(() => import("@/pages/UserDraftPage").then(m => ({ default: m.UserDraftPage }))),
  "player-forecast-vs-actual": PlayerForecastVsActualPage,
  "team-forecast-vs-actual": lazy(() => import("@/pages/TeamForecastVsActualPage").then(m => ({ default: m.TeamForecastVsActualPage }))),
  // Temporary stable alias for bookmarks from schema v4.
  "forecast-vs-actual": PlayerForecastVsActualPage,
  optimizer: lazy(() => import("@/pages/OptimizerAuditPage").then(m => ({ default: m.OptimizerAuditPage }))),
};

const LOCAL_ONLY_INSIGHTS: Record<string, string> = {
  "plan-builder": "This interactive decision workspace remains deterministic and local to the browser.",
  "squad-draft": "This browser-only draft workspace remains deterministic and local to the browser.",
};

function routeFromHash(): string {
  const fragment = window.location.hash.slice(1);
  const route = fragment.split("?", 1)[0] || DEFAULT_ROUTE;
  // The retired SDP player view duplicated FPL statistics. Preserve old bookmarks.
  const resolved = route === "players-stat-sdp" ? "players" : route;
  return Object.hasOwn(PAGES, resolved) && isPageAvailable(resolved) ? resolved : DEFAULT_ROUTE;
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
  const active = Object.hasOwn(PAGES, route) && isPageAvailable(route) ? route : DEFAULT_ROUTE;
  const Page = PAGES[active];

  return (
    <div className="flex h-screen">
      <Sidebar active={active} onNavigate={navigate} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end border-b px-4 py-2">
          <ThemeToggle />
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <PageBoundary key={active}>
            <Suspense fallback={<p role="status" className="p-6 text-sm text-muted-foreground">Loading page…</p>}>
              <Page />
            </Suspense>
          </PageBoundary>
          {LOCAL_ONLY_INSIGHTS[active] && (
            <div className="px-4 pb-6 lg:px-6">
              <InsightSummaryPanel
                items={[{ id: "local-only", statement: LOCAL_ONLY_INSIGHTS[active] }]}
                localOnlyReason="AI explanation is disabled on decision and private routes; no page state is sent."
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
