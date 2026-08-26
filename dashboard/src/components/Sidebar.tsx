// Left sidebar navigation. The hash route in App.tsx owns page selection. Collapses to
// icons-only on small screens (phone testing) and
// expands to labels from md up.

import {
  CalendarDays,
  ClipboardList,
  Goal,
  LayoutDashboard,
  LineChart,
  ListPlus,
  Scale,
  ScatterChart,
  Users,
  Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface PageDef {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const PAGES: readonly PageDef[] = [
  { id: "summary", label: "Summary", icon: LayoutDashboard },
  { id: "fixtures", label: "Fixture matrix", icon: CalendarDays },
  { id: "team-analytics", label: "Team analytics", icon: Goal },
  { id: "players", label: "Players", icon: Users },
  { id: "player-analytics", label: "Player analytics", icon: ScatterChart },
  { id: "next-gw", label: "Next GW suggestion", icon: ClipboardList },
  { id: "plan-builder", label: "Plan builder", icon: Wand2 },
  { id: "squad-draft", label: "Squad draft", icon: ListPlus },
  { id: "player-forecast-vs-actual", label: "Player prediction vs actual", icon: LineChart },
  { id: "team-forecast-vs-actual", label: "Team prediction vs actual", icon: LineChart },
  { id: "optimizer", label: "Optimizer audit", icon: Scale },
];

interface SidebarProps {
  active: string;
  onNavigate: (id: string) => void;
}

export function Sidebar({ active, onNavigate }: SidebarProps) {
  return (
    <nav
      aria-label="Pages"
      className="flex h-full w-14 shrink-0 flex-col border-r bg-sidebar md:w-56"
    >
      <div className="flex items-center gap-2 px-3 py-4 md:px-4">
        {/* ponytail: logo is a comet emoji, replace with a real mark if one exists */}
        <span className="text-xl">☄️</span>
        <div className="hidden md:block">
          <div className="text-sm font-semibold leading-tight">The Comet</div>
          <div className="text-xs text-muted-foreground">FPL decision dashboard</div>
        </div>
      </div>
      <ul className="flex-1 space-y-1 px-1.5 md:px-2">
        {PAGES.map((page) => {
          const Icon = page.icon;
          return (
            <li key={page.id}>
              <button
                type="button"
                onClick={() => onNavigate(page.id)}
                aria-current={active === page.id ? "page" : undefined}
                title={page.label}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm max-md:justify-center max-md:px-0",
                  active === page.id
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50",
                )}
              >
                <Icon className="size-4 shrink-0" />
                <span className="flex-1 truncate max-md:hidden">{page.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="hidden px-4 py-3 text-[10px] leading-snug text-muted-foreground md:block">
        Reads only the static JSON read models exported by the publish layer. It never
        queries DuckDB.
      </p>
    </nav>
  );
}
