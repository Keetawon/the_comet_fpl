// Plan builder (the wizard, v1). Screens 1-3 of the design record
// (docs/manager-team-suggestions.md): Start (import vs scratch), Set your rules (lock picker
// with search/filters, per-position and club-cap guards, live budget pre-flight, rotation
// threshold), and Review. Screen 4 is the command bridge: the browser cannot solve (the
// optimizer is PuLP/CBC in Python), so the wizard emits the exact command to run and the
// result renders through the existing Next GW page once recorded. The manager_id import
// collects the id now and lands as a P2 job after the deadline — never faked.

import { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, ArrowRight, Check, Download, Lock, RotateCcw, Sparkles, UserRoundSearch } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import type { PlayerRecord } from "@/data/types";
import { isDefaultArchitecture } from "@/lib/nextGw";
import { availabilityLabel } from "@/lib/availability";
import { cn } from "@/lib/utils";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; players: PlayerRecord[]; runId: string | null };

type Mode = "choose" | "import" | "scratch";

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;
const MAX_LOCKS = 5;
const THRESHOLDS = [
  { value: "off", label: "Off", flag: null },
  { value: "0.25", label: "25%", flag: "0.25" },
  { value: "0.5", label: "50%", flag: "0.5" },
] as const;
const STEPS = ["Start", "Set your rules", "Run it"] as const;

const price = (tenths: number | null) => (tenths == null ? "–" : `£${(tenths / 10).toFixed(1)}m`);

interface Rules {
  squadQuota: Record<string, number>;
  budgetTenths: number;
  maxPerClub: number;
}

/** Squad rules come from the recorded optimizer artifacts (rules snapshot), never hardcoded. */
function rulesFromAudit(audit: { plans: { rules_snapshot: { squad_size: number; budget_tenths: number; maximum_per_club: number; positions: { position: string; squad: number }[] } }[] } | null): Rules | null {
  const snapshot = audit?.plans?.[0]?.rules_snapshot;
  if (!snapshot) return null;
  return {
    squadQuota: Object.fromEntries(snapshot.positions.map((p) => [p.position, p.squad])),
    budgetTenths: snapshot.budget_tenths,
    maxPerClub: snapshot.maximum_per_club,
  };
}

function StepBar({ active }: { active: readonly number[] }) {
  const first = Math.min(...active);
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Wizard steps">
      {STEPS.map((label, index) => {
        const step = index + 1;
        const state = active.includes(step) ? "active" : step < first ? "done" : "todo";
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                state === "active" && "border-primary bg-primary/10 text-primary",
                state === "done" && "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
                state === "todo" && "border-border text-muted-foreground",
              )}
            >
              <span
                className={cn(
                  "flex size-4 items-center justify-center rounded-full text-[9px] font-semibold",
                  state === "active" && "bg-primary text-primary-foreground",
                  state === "done" && "bg-emerald-500 text-white",
                  state === "todo" && "bg-muted text-muted-foreground",
                )}
              >
                {state === "done" ? <Check className="size-3" /> : step}
              </span>
              {label}
            </span>
            {index < STEPS.length - 1 && <span aria-hidden className="h-px w-4 bg-border md:w-8" />}
          </li>
        );
      })}
    </ol>
  );
}

export function PlanBuilderPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [rules, setRules] = useState<Rules | null>(null);
  const [mode, setMode] = useState<Mode>("choose");
  const [managerId, setManagerId] = useState("");
  const [locks, setLocks] = useState<PlayerRecord[]>([]);
  const [threshold, setThreshold] = useState<string>("off");
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("all");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadNextGw(), loadOptimizerAudit()])
      .then(([playersData, nextGw, audit]) => {
        if (cancelled) return;
        const defaultRun =
          nextGw.plans.find((p) => isDefaultArchitecture(p.component_modes))?.forecast_run_id ??
          playersData.manifest?.runs.at(-1)?.run_id ??
          playersData.players[0]?.run_id ??
          null;
        setState({
          status: "ready",
          players: playersData.players.filter((p) => p.run_id === defaultRun),
          runId: defaultRun,
        });
        setRules(rulesFromAudit(audit));
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const budget = rules?.budgetTenths ?? 1000;
  const quota = rules?.squadQuota ?? { GK: 2, DEF: 5, MID: 5, FWD: 3 };
  const maxPerClub = rules?.maxPerClub ?? 3;

  const totals = useMemo(() => {
    if (state.status !== "ready") return null;
    const lockedCost = locks.reduce((sum, p) => sum + (p.now_cost ?? 0), 0);
    const lockedByPos: Record<string, number> = {};
    const lockedByClub: Record<number, number> = {};
    for (const p of locks) {
      lockedByPos[p.position] = (lockedByPos[p.position] ?? 0) + 1;
      lockedByClub[p.team_code] = (lockedByClub[p.team_code] ?? 0) + 1;
    }
    // Cheapest legal completion is a lower bound: the k cheapest remaining players per
    // position, ignoring the club cap (rare; the solver names it if it ever binds).
    let completion = 0;
    for (const pos of POSITIONS) {
      const remaining = (quota[pos] ?? 0) - (lockedByPos[pos] ?? 0);
      const lockedCodes = new Set(locks.map((p) => p.code));
      const cheapest = state.players
        .filter((p) => p.position === pos && !lockedCodes.has(p.code) && p.now_cost != null)
        .map((p) => p.now_cost ?? 0)
        .sort((a, b) => a - b)
        .slice(0, Math.max(0, remaining));
      completion += cheapest.reduce((a, b) => a + b, 0);
    }
    return { lockedCost, completion, leftover: budget - lockedCost - completion, lockedByPos, lockedByClub };
  }, [state, locks, quota, budget]);

  const guard = (player: PlayerRecord): string | null => {
    if (locks.some((p) => p.code === player.code)) return null;
    if (locks.length >= MAX_LOCKS) return `max ${MAX_LOCKS} locks`;
    if ((totals?.lockedByPos[player.position] ?? 0) >= (quota[player.position] ?? 0)) {
      return `${player.position} quota full`;
    }
    if ((totals?.lockedByClub[player.team_code] ?? 0) >= maxPerClub) {
      return "club cap (3)";
    }
    return null;
  };

  const toggleLock = (player: PlayerRecord) => {
    if (guard(player)) return;
    setLocks((current) =>
      current.some((p) => p.code === player.code)
        ? current.filter((p) => p.code !== player.code)
        : [...current, player],
    );
  };

  const candidates = useMemo(() => {
    if (state.status !== "ready") return [];
    const term = search.trim().toLowerCase();
    return state.players
      .filter((p) => (position === "all" || p.position === position) && p.now_cost != null)
      .filter((p) => !term || (p.web_name ?? "").toLowerCase().includes(term))
      .map((p) => ({
        player: p,
        xp: p.fixtures.reduce((sum, f) => sum + (f.expected_points ?? 0), 0),
      }))
      .sort((a, b) => b.xp - a.xp || (a.player.now_cost ?? 0) - (b.player.now_cost ?? 0))
      .slice(0, 50);
  }, [state, search, position]);

  const thresholdFlag = THRESHOLDS.find((t) => t.value === threshold)?.flag ?? null;
  const command = [
    ".\\.venv\\Scripts\\python.exe -m fpl.jobs.optimize_squad <forecast.jsonl>",
    "--risk-lambda 0",
    ...locks.map((p) => `--lock ${p.code}`),
    ...(thresholdFlag ? [`--min-bench-appearance ${thresholdFlag}`] : []),
    "--output <plan.json>",
  ].join(" ");

  const managerTouched = managerId.trim() !== "";
  const managerValid = /^\d{1,10}$/.test(managerId.trim());
  const activeSteps = mode === "scratch" ? [2, 3] : [1];

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Plan builder</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!rules) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Plan builder</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No optimizer artifact is loaded, so the squad rules snapshot is unavailable. Rebuild
          the read models with --optimizer-plan inputs first.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Plan builder</h1>
        <p className="text-xs text-muted-foreground">
          vintage {state.runId?.slice(0, 12)}… · rules from the recorded optimizer artifact ·
          wizard v1 (fresh squad); manager import lands after GW1
        </p>
      </div>
      <StepBar active={activeSteps} />

      {mode === "choose" && (
        <section className="mx-auto grid w-full max-w-3xl gap-4 pt-2 md:grid-cols-2" aria-label="Start">
          <button
            type="button"
            onClick={() => setMode("import")}
            className="group relative overflow-hidden rounded-xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-sky-400 to-indigo-500" />
            <span className="flex size-10 items-center justify-center rounded-lg bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-300">
              <UserRoundSearch className="size-5" />
            </span>
            <p className="mt-3 font-semibold">Import my team</p>
            <Badge variant="outline" className="mt-1.5 border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Lands after the GW1 deadline
            </Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Enter your FPL manager id and get transfer suggestions for <em>your</em> squad —
              banked free transfers and -4 hits accounted.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary transition-transform group-hover:translate-x-0.5">
              Enter manager id <ArrowRight className="size-3" />
            </span>
          </button>
          <button
            type="button"
            onClick={() => setMode("scratch")}
            className="group relative overflow-hidden rounded-xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-400 to-orange-500" />
            <span className="flex size-10 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-950 dark:text-amber-300">
              <Sparkles className="size-5" />
            </span>
            <p className="mt-3 font-semibold">Build from scratch →</p>
            <Badge variant="outline" className="mt-1.5 border-emerald-300 bg-emerald-50 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
              Ready now
            </Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              Lock up to {MAX_LOCKS} must-keep players, set the bench rotation threshold, and
              take the exact optimizer command from here.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary transition-transform group-hover:translate-x-0.5">
              Start configuring <ArrowRight className="size-3" />
            </span>
          </button>
        </section>
      )}

      {mode === "import" && (
        <section className="mx-auto w-full max-w-2xl space-y-4 pt-2" aria-label="Import my team">
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold">Import my team</h2>
              <Badge variant="outline" className="border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                Lands after the GW1 deadline (2026-08-21)
              </Badge>
            </div>
            <label htmlFor="manager-id" className="mt-4 block text-sm font-medium">
              FPL manager id
            </label>
            <Input
              id="manager-id"
              inputMode="numeric"
              placeholder="e.g. 1234567"
              aria-invalid={managerTouched && !managerValid}
              aria-describedby="manager-id-hint"
              className="mt-1 max-w-xs font-mono"
              value={managerId}
              onChange={(e) => {
                setManagerId(e.target.value);
                // remembered locally so the import screen greets a returning user once it ships
                if (/^\d{1,10}$/.test(e.target.value.trim())) {
                  try { localStorage.setItem("fpl-manager-id", e.target.value.trim()); } catch { /* private mode */ }
                }
              }}
            />
            <p id="manager-id-hint" className="mt-1.5 text-xs text-muted-foreground">
              {managerTouched && !managerValid
                ? "Digits only — it's the number in fantasy.premierleague.com/entry/{id}."
                : "The number in fantasy.premierleague.com/entry/{id}."}
            </p>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              {managerTouched && managerValid
                ? `Manager #${managerId.trim()} saved — the importer will read this team first once it ships.`
                : "Your id is remembered on this device; nothing is sent anywhere (this dashboard is static)."}
            </p>
          </div>
          <div className="rounded-xl border bg-muted/40 p-4">
            <p className="text-xs font-medium text-muted-foreground">What the importer will do once it lands</p>
            <ul className="mt-2 space-y-2 text-sm">
              {[
                { icon: Download, text: "Read your 15 with real selling prices and bank — the dashboard never fetches; a local job captures and publishes." },
                { icon: ArrowLeftRight, text: "Derive your banked free transfers so hits are charged honestly (-4 each beyond the free grant)." },
                { icon: Lock, text: "Suggest transfers for YOUR squad — locks become never-sell, the rotation threshold still applies." },
              ].map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-start gap-2">
                  <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span className="text-xs leading-relaxed text-muted-foreground">{text}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => setMode("scratch")}>
              Continue without import <ArrowRight className="size-4" />
            </Button>
            <Button variant="ghost" onClick={() => setMode("choose")}>Back</Button>
          </div>
        </section>
      )}

      {mode === "scratch" && totals && (
        <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
          <section aria-label="Lock picker" className="rounded-lg border bg-muted/40 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                Lock picker — pick up to {MAX_LOCKS} must-keep players
              </p>
              <div className="flex items-center gap-2">
                <Badge
                  variant={locks.length ? "default" : "outline"}
                  className={cn("tabular-nums", locks.length === MAX_LOCKS && "bg-amber-500")}
                >
                  <Lock className="size-3" /> {locks.length}/{MAX_LOCKS}
                </Badge>
                {locks.length > 0 && (
                  <Button variant="ghost" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setLocks([])}>
                    Clear all
                  </Button>
                )}
              </div>
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Input
                placeholder="Search player…"
                aria-label="Search player"
                className="h-8 w-44"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <Select value={position} onValueChange={setPosition}>
                <SelectTrigger size="sm" className="w-24" aria-label="Position filter">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  {POSITIONS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="text-xs text-muted-foreground">
                top {candidates.length} by GW xP
              </span>
            </div>
            <ul className="grid gap-1.5 md:grid-cols-1 lg:grid-cols-2">
              {candidates.map(({ player, xp }) => {
                const locked = locks.some((p) => p.code === player.code);
                const blocked = guard(player);
                return (
                  <li key={player.code}>
                    <button
                      type="button"
                      onClick={() => toggleLock(player)}
                      disabled={!!blocked && !locked}
                      aria-pressed={locked}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg border bg-card px-2 py-1.5 text-left text-xs transition-all",
                        locked
                          ? "border-amber-400/80 bg-amber-50 ring-1 ring-amber-400/60 dark:bg-amber-950/40"
                          : "hover:-translate-y-px hover:border-primary/40 hover:shadow-sm",
                        blocked && !locked && "cursor-not-allowed opacity-50 hover:translate-y-0 hover:border-border hover:shadow-none",
                      )}
                    >
                      <PlayerPhoto code={player.code} name={player.web_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">
                          {player.web_name}
                          {locked && <Badge className="ml-1 px-1 text-[9px]">locked</Badge>}
                        </span>
                        <span className="flex items-center gap-1 text-muted-foreground">
                          <TeamBadge teamCode={player.team_code} shortName={player.team_short_name} />
                          {player.position} · {price(player.now_cost)} ·{" "}
                          {(player.selected_by_percent ?? 0).toFixed(1)}% ·{" "}
                          {availabilityLabel(player.availability_status)}
                        </span>
                      </span>
                      <span className="text-right">
                        <span className="block tabular-nums font-medium">{xp.toFixed(1)}</span>
                        <span className="block text-[9px] text-muted-foreground">GW xP</span>
                      </span>
                      {locked ? (
                        <Lock className="size-3.5 shrink-0 text-amber-500" />
                      ) : blocked ? (
                        <span className="text-[9px] text-muted-foreground">{blocked}</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          <section aria-label="Review" className="flex flex-col gap-3">
            <div className="rounded-xl border bg-card p-3 shadow-sm">
              <p className="mb-2 text-xs font-medium text-muted-foreground">Review your rules</p>
              {locks.length ? (
                <ul className="flex flex-wrap gap-1.5" aria-label="Locked players">
                  {locks.map((p) => (
                    <li
                      key={p.code}
                      className="flex items-center gap-1.5 rounded-full border border-amber-300/70 bg-amber-50 py-0.5 pl-1 pr-1.5 text-xs dark:border-amber-700 dark:bg-amber-950/40"
                    >
                      <PlayerPhoto code={p.code} name={p.web_name} size="sm" />
                      <span className="font-medium">{p.web_name}</span>
                      <span className="text-muted-foreground">{price(p.now_cost)}</span>
                      <button
                        type="button"
                        aria-label={`Remove ${p.web_name}`}
                        onClick={() => setLocks((current) => current.filter((x) => x.code !== p.code))}
                        className="rounded-full px-1 text-muted-foreground transition-colors hover:bg-amber-100 hover:text-foreground dark:hover:bg-amber-900/60"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No locks — the optimizer picks all 15.</p>
              )}
              <div className="mt-3 flex items-center gap-2 text-sm">
                Rotation threshold
                <ToggleGroup
                  type="single"
                  value={threshold}
                  onValueChange={(value) => value && setThreshold(value)}
                  variant="outline"
                  size="sm"
                  aria-label="Rotation threshold"
                >
                  {THRESHOLDS.map((t) => (
                    <ToggleGroupItem key={t.value} value={t.value}>
                      {t.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Outfield bench players must be at least this likely to appear; bench goalkeeper
                exempt.
              </p>
              <div className="mt-3">
                <div
                  role="img"
                  aria-label={`Budget meter: locked ${price(totals.lockedCost)}, cheapest fill ${price(totals.completion)}, budget ${price(budget)}`}
                  className="flex h-2.5 overflow-hidden rounded-full bg-muted"
                >
                  <div
                    className="bg-primary transition-all"
                    style={{ width: `${Math.min(100, (totals.lockedCost / budget) * 100)}%` }}
                  />
                  <div
                    className="bg-primary/35 transition-all"
                    style={{
                      width: `${totals.leftover < 0 ? 100 - Math.min(100, (totals.lockedCost / budget) * 100) : Math.min(100 - (totals.lockedCost / budget) * 100, (totals.completion / budget) * 100)}%`,
                    }}
                  />
                  {totals.leftover < 0 && (
                    <div className="flex-1 bg-destructive transition-all" />
                  )}
                </div>
                <div className="mt-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
                  <span className="flex items-center gap-2 tabular-nums">
                    <span className="inline-block size-2 rounded-full bg-primary" />
                    locked {price(totals.lockedCost)}
                    <span className="inline-block size-2 rounded-full bg-primary/35" />
                    cheapest fill {price(totals.completion)}
                  </span>
                  <span className="tabular-nums">budget {price(budget)}</span>
                </div>
                <div
                  className={cn(
                    "mt-1 text-xs tabular-nums",
                    totals.leftover < 0
                      ? "font-medium text-destructive"
                      : totals.lockedCost / budget > 0.9
                        ? "font-medium text-amber-600 dark:text-amber-400"
                        : "text-muted-foreground",
                  )}
                >
                  {totals.leftover < 0
                    ? `over budget by ${price(-totals.leftover)} — unlock a player`
                    : `headroom ${price(totals.leftover)}${totals.lockedCost / budget > 0.9 ? " (warning: >90% committed)" : ""}`}
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
              <div className="flex items-center justify-between gap-2 border-b bg-zinc-900 px-3 py-1.5 dark:bg-zinc-900">
                <p className="font-mono text-[11px] text-zinc-300">optimizer command</p>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[11px] text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                  onClick={() => {
                    void navigator.clipboard?.writeText(command).then(() => {
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1500);
                    });
                  }}
                >
                  {copied ? <Check className="size-3" /> : null}
                  {copied ? "Copied" : "Copy command"}
                </Button>
              </div>
              <pre className="overflow-x-auto bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-100">
                {command}
              </pre>
              <p className="px-3 py-2 text-[10px] text-muted-foreground">
                The solver lives in Python, so the browser cannot compute it. forecast.jsonl =
                the default GW1-5 artifact from the latest pack (see the runbook); the written
                plan.json renders on the Next GW page once the export includes it.
              </p>
              <div className="flex items-center gap-2 px-3 pb-3">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setMode("choose");
                    setLocks([]);
                    setThreshold("off");
                    setSearch("");
                    setPosition("all");
                  }}
                >
                  <RotateCcw className="size-3.5" /> Start over
                </Button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
