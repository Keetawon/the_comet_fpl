// Left sidebar navigation. All six planned pages are listed in roadmap order; only the
// Fixture matrix is implemented in P1.7b -- the rest are labelled stubs.

import {
  CalendarDays,
  ClipboardList,
  LayoutDashboard,
  LineChart,
  Scale,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface PageDef {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  ready: boolean;
}

const PAGES: readonly PageDef[] = [
  { id: "summary", label: "Summary", icon: LayoutDashboard, ready: true },
  { id: "fixtures", label: "Fixture matrix", icon: CalendarDays, ready: true },
  { id: "players", label: "Players", icon: Users, ready: true },
  { id: "next-gw", label: "Next GW suggestion", icon: ClipboardList, ready: true },
  { id: "forecast-vs-actual", label: "Forecast vs actual", icon: LineChart, ready: true },
  { id: "optimizer", label: "Optimizer audit", icon: Scale, ready: true },
];

interface SidebarProps {
  active: string;
  onNavigate: (id: string) => void;
}

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <nav aria-label="Pages" className="flex h-full w-56 shrink-0 flex-col border-r bg-sidebar">
      <div className="flex items-center gap-2 px-4 py-4">
        {/* ponytail: logo is a comet emoji, replace with a real mark if one exists */}
        <span className="text-xl">☄️</span>
        <div>
          <div className="text-sm font-semibold leading-tight">The Comet</div>
          <div className="text-xs text-muted-foreground">FPL decision dashboard</div>
        </div>
      </div>
      <ul className="flex-1 space-y-1 px-2">
        {PAGES.map((page) => {
          const Icon = page.icon;
          return (
            <li key={page.id}>
              <button
                type="button"
                onClick={() => onNavigate(page.id)}
                aria-current={active === page.id ? "page" : undefined}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm",
                  active === page.id
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50",
                  !page.ready && "opacity-60",
                )}
              >
                <Icon className="size-4" />
                <span className="flex-1">{page.label}</span>
                {!page.ready && (
                  <span className="text-[10px] text-muted-foreground">soon</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="px-4 py-3 text-[10px] leading-snug text-muted-foreground">
        Reads only the static JSON read models exported by the publish layer. It never
        queries DuckDB.
      </p>
    </nav>
  );
}
