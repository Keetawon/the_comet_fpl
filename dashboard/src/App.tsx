// App shell: sidebar navigation over a tiny hash route (no router dependency). An unknown
// hash falls back to the Summary landing page.

import { lazy, Suspense, useEffect, useId, useRef, useState } from "react";
import { LayoutDashboard, Menu, MoreHorizontal, Newspaper, Users, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { CometMark, PageBreadcrumb, Sidebar } from "@/components/Sidebar";
import { PageBoundary } from "@/components/PageBoundary";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { ThemeToggle, initTheme } from "@/components/ThemeToggle";
import { isPageAvailable } from "@/lib/pageAccess";

const SummaryPage = lazy(() => import("@/pages/SummaryPage").then(m => ({ default: m.SummaryPage })));
const PlayerForecastVsActualPage = lazy(() => import("@/pages/PlayerForecastVsActualPage").then(m => ({ default: m.PlayerForecastVsActualPage })));

const DEFAULT_ROUTE = "summary";
const SIDEBAR_PREFERENCE = "comet:sidebar-collapsed";
const MOBILE_PAGES = [
  { id: "summary", label: "Summary", icon: LayoutDashboard },
  { id: "news", label: "News", icon: Newspaper },
  { id: "players", label: "Players", icon: Users },
] as const;

function sidebarPreference(): boolean {
  try { return window.localStorage.getItem(SIDEBAR_PREFERENCE) === "true"; }
  catch { return false; }
}

const PAGES: Record<string, React.ComponentType> = {
  summary: SummaryPage,
  news: lazy(() => import("@/pages/NewsPage").then(m => ({ default: m.NewsPage }))),
  "score-prediction": lazy(() => import("@/pages/GwAnalysisPage").then(m => ({ default: m.GwAnalysisPage }))),
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
  const resolved = route === "players-stat-sdp" ? "players" : route === "gw-analysis" ? "score-prediction" : route;
  return Object.hasOwn(PAGES, resolved) && isPageAvailable(resolved) ? resolved : DEFAULT_ROUTE;
}

function useHashRoute(): [string, (id: string) => void] {
  const [route, setRoute] = useState(routeFromHash);
  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash;
      // Canonicalize old shared links without adding a browser-history entry.
      if (hash.split("?", 1)[0] === "#gw-analysis") {
        window.history.replaceState(window.history.state, "", hash.replace("#gw-analysis", "#score-prediction"));
      }
      setRoute(routeFromHash());
    };
    window.addEventListener("hashchange", onHashChange);
    onHashChange();
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
  const [menuOpen, setMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(sidebarPreference);
  const menuTrigger = useRef<HTMLButtonElement | null>(null);
  const mobileMenuId = useId();
  const active = Object.hasOwn(PAGES, route) && isPageAvailable(route) ? route : DEFAULT_ROUTE;
  const Page = PAGES[active];

  useEffect(() => {
    const close = () => setMenuOpen(false);
    window.addEventListener("hashchange", close);
    // A mobile drawer must not leave scroll/focus locked after rotating to desktop.
    const desktop = window.matchMedia?.("(min-width: 768px)");
    const onResize = () => { if (desktop?.matches) close(); };
    desktop?.addEventListener("change", onResize);
    return () => {
      window.removeEventListener("hashchange", close);
      desktop?.removeEventListener("change", onResize);
    };
  }, []);

  const visit = (id: string) => { setMenuOpen(false); navigate(id); };
  const openMenu = (event: React.MouseEvent<HTMLButtonElement>) => {
    menuTrigger.current = event.currentTarget;
    setMenuOpen(true);
  };
  const toggleSidebar = () => {
    const collapsed = !sidebarCollapsed;
    setSidebarCollapsed(collapsed);
    try { window.localStorage.setItem(SIDEBAR_PREFERENCE, String(collapsed)); }
    catch { /* Navigation still works when browser storage is disabled. */ }
  };

  return (
    <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
    <div className="comet-shell flex h-dvh overflow-hidden">
      <div className="comet-desktop-navigation hidden shrink-0 md:block">
        <Sidebar active={active} onNavigate={visit} collapsed={sidebarCollapsed} onToggleCollapse={toggleSidebar} />
      </div>
      <div className="comet-workspace flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="comet-topbar flex min-h-16 shrink-0 items-center gap-3 px-3 py-2 md:justify-end md:px-6">
          <button type="button" onClick={openMenu} aria-label="Open navigation" aria-haspopup="dialog"
            aria-expanded={menuOpen} aria-controls={mobileMenuId}
            className="comet-nav-toggle flex size-11 shrink-0 items-center justify-center rounded-xl md:hidden">
            <Menu className="size-6" aria-hidden />
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 md:hidden">
            <CometMark className="size-8 shrink-0" />
            <div className="min-w-0"><div className="truncate text-sm font-bold">The Comet FPL</div>
              <div className="text-[11px] text-muted-foreground">Your gameweek, clearer.</div></div>
          </div>
          <PageBreadcrumb active={active} />
          <ThemeToggle />
        </header>
        <main id="main-content" className="comet-main relative min-h-0 flex-1 overflow-auto">
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
        <nav aria-label="Quick navigation" className="comet-bottom-nav grid shrink-0 grid-cols-4 md:hidden">
          {MOBILE_PAGES.map(({ id, label, icon: Icon }) => <button type="button" key={id} onClick={() => visit(id)}
            aria-current={active === id ? "page" : undefined}
            className="comet-bottom-item flex min-h-16 flex-col items-center justify-center gap-1 px-2 py-2 text-[11px] font-medium">
            <Icon className="size-5" aria-hidden /><span>{label}</span>
          </button>)}
          <button type="button" onClick={openMenu} aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls={mobileMenuId}
            className="comet-bottom-item flex min-h-16 flex-col items-center justify-center gap-1 px-2 py-2 text-[11px] font-medium">
            <MoreHorizontal className="size-5" aria-hidden /><span>More</span>
          </button>
        </nav>
      </div>
    </div>
    <Dialog.Portal>
      <Dialog.Overlay className="comet-menu-overlay fixed inset-0 z-50 bg-black/45 backdrop-blur-sm md:hidden" />
      <Dialog.Content id={mobileMenuId} aria-describedby={undefined}
        className="comet-mobile-drawer fixed inset-y-0 left-0 z-50 flex w-[min(88vw,22rem)] flex-col bg-sidebar shadow-2xl md:hidden"
        onCloseAutoFocus={event => { event.preventDefault(); menuTrigger.current?.focus(); }}>
        <div className="flex shrink-0 items-center justify-between px-4 py-2">
          <Dialog.Title className="text-sm font-semibold">Explore The Comet</Dialog.Title>
          <Dialog.Close aria-label="Close navigation" className="comet-nav-toggle flex size-11 items-center justify-center rounded-xl">
            <X className="size-5" aria-hidden />
          </Dialog.Close>
        </div>
        <div className="min-h-0 flex-1"><Sidebar active={active} onNavigate={visit} variant="drawer" /></div>
      </Dialog.Content>
    </Dialog.Portal>
    </Dialog.Root>
  );
}
