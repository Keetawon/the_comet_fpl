// Shared page navigation for the desktop rail and the dismissible mobile drawer.

import {
  CalendarDays,
  ClipboardList,
  Goal,
  LayoutDashboard,
  LineChart,
  ListPlus,
  Newspaper,
  FileText,
  Scale,
  ScatterChart,
  Users,
  Wand2,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SupportButton } from "./SupportButton";
import { isPageAvailable } from "@/lib/pageAccess";

/** Compact vector mark drawn from the owner's cyan comet design. */
export function CometMark({ className }: { className?: string }) {
  return <svg viewBox="0 0 40 40" fill="none" className={cn("comet-brand-mark", className)} aria-hidden="true">
    <path d="M27 7 10 24a6.4 6.4 0 0 0 9 9L35 17" fill="currentColor" fillOpacity=".2"
      stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="m19 5-7 7M31 4 20 15m16-6-8 8" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" />
    <path d="m13 24-1 1a3.2 3.2 0 0 0 4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" opacity=".6" />
  </svg>;
}

export interface PageDef {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const PAGES: readonly PageDef[] = [
  { id: "summary", label: "Summary", icon: LayoutDashboard },
  { id: "news", label: "News", icon: Newspaper },
  { id: "gw-analysis", label: "Score Prediction", icon: FileText },
  { id: "fixtures", label: "Fixture matrix", icon: CalendarDays },
  { id: "team-analytics", label: "Team analytics", icon: Goal },
  { id: "team-stat-sdp", label: "Team stat from SDP", icon: Goal },
  { id: "players", label: "Players", icon: Users },
  { id: "player-analytics", label: "Player analytics", icon: ScatterChart },
  { id: "next-gw", label: "Next GW suggestion", icon: ClipboardList },
  { id: "plan-builder", label: "Plan builder", icon: Wand2 },
  { id: "squad-draft", label: "Squad draft", icon: ListPlus },
  { id: "player-forecast-vs-actual", label: "Player prediction vs actual", icon: LineChart },
  { id: "team-forecast-vs-actual", label: "Team prediction vs actual", icon: LineChart },
  { id: "optimizer", label: "Optimizer audit", icon: Scale },
];

export function PageBreadcrumb({ active }: { active: string }) {
  const route = active === "forecast-vs-actual" ? "player-forecast-vs-actual" : active;
  const label = PAGES.find(page => page.id === route)?.label ?? "Summary";
  return <div className="comet-breadcrumb hidden min-w-0 flex-1 items-center gap-2 text-sm md:flex">
    <span className="text-muted-foreground">The Comet</span><span aria-hidden className="text-muted-foreground">/</span>
    <span className="truncate font-medium">{label}</span>
  </div>;
}

interface SidebarProps {
  active: string;
  onNavigate: (id: string) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  variant?: "desktop" | "drawer";
}

export function Sidebar({ active, onNavigate, collapsed = false, onToggleCollapse, variant = "desktop" }: SidebarProps) {
  return (
    <nav
      aria-label={variant === "drawer" ? "All pages" : "Pages"}
      data-collapsed={collapsed}
      data-variant={variant}
      className={cn("comet-sidebar flex h-full shrink-0 flex-col", collapsed ? "w-20" : "w-64", variant === "drawer" && "w-full")}
    >
      <div className={cn("comet-sidebar-brand flex gap-2 px-4 py-5", collapsed ? "flex-col items-center" : "items-center")}>
        <CometMark className="size-8 shrink-0" />
        {!collapsed && <div className="min-w-0 flex-1">
          <div className="text-sm font-bold leading-tight">The Comet FPL</div>
          <div className="mt-1 text-xs text-muted-foreground">Your gameweek, clearer.</div>
        </div>}
        {onToggleCollapse && <button type="button" onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="comet-nav-toggle flex size-11 shrink-0 items-center justify-center rounded-xl hover:bg-sidebar-accent">
          {collapsed ? <PanelLeftOpen className="size-5" aria-hidden /> : <PanelLeftClose className="size-5" aria-hidden />}
        </button>}
      </div>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3">
        {PAGES.filter((page) => isPageAvailable(page.id)).map((page) => {
          const Icon = page.icon;
          return (
            <li key={page.id}>
              <button
                type="button"
                onClick={() => onNavigate(page.id)}
                aria-current={active === page.id ? "page" : undefined}
                aria-label={page.label}
                title={page.label}
                className={cn(
                  "comet-nav-item flex min-h-11 w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm",
                  collapsed && "justify-center px-0",
                  active === page.id
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50",
                )}
              >
                <Icon className="size-5 shrink-0" aria-hidden />
                {!collapsed && <span className="flex-1">{page.label}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <div className={cn("comet-sidebar-support shrink-0 px-3 pt-3 pb-2 [&_a]:min-h-11", collapsed ? "[&_a]:px-0 [&_span]:hidden" : "[&_span]:inline")}>
        <SupportButton />
      </div>
      {!collapsed && <p className="px-4 py-3 text-[10px] leading-snug text-muted-foreground">
        Independent FPL insights. Your team, your call.
      </p>}
    </nav>
  );
}
