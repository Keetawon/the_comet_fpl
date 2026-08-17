// A visually distinct panel for filter controls, so "this is where I filter" reads
// instantly against the plain table below it.

import type { ReactNode } from "react";
import { ListFilter } from "lucide-react";

export function FilterPanel({ children }: { children: ReactNode }) {
  return (
    <section
      aria-label="Filters"
      className="rounded-lg border bg-muted/40 p-3 shadow-xs"
    >
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <ListFilter className="size-3.5" aria-hidden />
        Filters
      </div>
      {children}
    </section>
  );
}
