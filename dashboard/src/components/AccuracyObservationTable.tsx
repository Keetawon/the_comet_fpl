import { useState, type ReactNode } from "react";
import { DecisionTableFullscreen } from "./DecisionTableFullscreen";
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from "./ui/table";

export interface AccuracyColumn<T> {
  key: string;
  label: string;
  value: (row: T) => string | number | null;
  render?: (row: T) => ReactNode;
  advanced?: boolean;
}

/** Sort and inspect published observations. Does not recalculate scorecards. */
export function AccuracyObservationTable<T>({ title, rows, columns, rowKey, searchText, context }: {
  title: string;
  rows: readonly T[];
  columns: readonly AccuracyColumn<T>[];
  rowKey: (row: T) => string;
  searchText: (row: T) => string;
  context: string;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState({ key: "error", desc: true });
  const [page, setPage] = useState(0);
  const [advanced, setAdvanced] = useState(false);
  const selected = columns.find((c) => c.key === sort.key);
  const filtered = rows.filter((r) => searchText(r).toLowerCase().includes(query.trim().toLowerCase()));
  const ordered = [...filtered].sort((a, b) => {
    if (!selected) return 0;
    const x = selected.value(a), y = selected.value(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    const result = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return (sort.desc ? -result : result) || rowKey(a).localeCompare(rowKey(b));
  });
  const pages = Math.max(1, Math.ceil(ordered.length / 50));
  const current = Math.min(page, pages - 1);
  const visible = ordered.slice(current * 50, (current + 1) * 50);
  const shown = columns.filter((c) => advanced || !c.advanced);
  return <section className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-semibold">{title}</h2>
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label={`Search ${title}`} placeholder="Search name, club or GW…" className="h-9 w-64 max-w-full rounded-md border bg-background px-3 text-sm" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />Detailed metrics</label>
        <button className="text-sm underline" onClick={() => { setQuery(""); setSort({ key: "error", desc: true }); setPage(0); setAdvanced(false); }}>Reset table</button>
      </div>
    </div>
    <p className="text-xs text-muted-foreground">Forecast and actual are side by side. Δ = actual − forecast. Largest errors first. Search and sorting affect this table only; charts and scorecards retain the selected GW scope.</p>
    <DecisionTableFullscreen label={title} captureContext={`${context} · ${filtered.length} matching rows · page ${current + 1}/${pages} · published observations only`}>
      <div className="rounded-md border">
        <Table aria-label={title} containerClassName="max-h-[36rem] overflow-auto"><TableHeader className="sticky top-0 z-10 bg-card"><TableRow>{shown.map((c) => <TableHead key={c.key} aria-sort={sort.key === c.key ? sort.desc ? "descending" : "ascending" : "none"}>
          <button className="whitespace-nowrap py-2 font-medium" onClick={() => { setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : true }); setPage(0); }}>{c.label}{sort.key === c.key ? sort.desc ? " ↓" : " ↑" : ""}</button>
        </TableHead>)}</TableRow></TableHeader><TableBody>
          {visible.map((r) => <TableRow key={rowKey(r)}>{shown.map((c) => <TableCell key={c.key} className="whitespace-nowrap py-2 tabular-nums">{c.render ? c.render(r) : c.value(r) ?? "—"}</TableCell>)}</TableRow>)}
          {!visible.length && <TableRow><TableCell colSpan={shown.length}>No scored observations match this scope. Pending or missing results are not zero.</TableCell></TableRow>}
        </TableBody></Table>
      </div>
      <div className="flex items-center justify-between gap-3 py-2 text-xs text-muted-foreground"><span>{ordered.length ? current * 50 + 1 : 0}–{Math.min((current + 1) * 50, ordered.length)} of {ordered.length}</span><div className="flex gap-4"><button disabled={!current} onClick={() => setPage(current - 1)}>Previous</button><span>Page {current + 1}/{pages}</span><button disabled={current + 1 >= pages} onClick={() => setPage(current + 1)}>Next</button></div></div>
    </DecisionTableFullscreen>
  </section>;
}

export function AccuracyDelta({ value, digits = 2 }: { value: number; digits?: number }) {
  return <span className={`rounded px-2 py-1 text-xs font-medium ${value > 0 ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" : value < 0 ? "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200" : "bg-muted"}`}>{value > 0 ? "+" : ""}{value.toFixed(digits)}</span>;
}
