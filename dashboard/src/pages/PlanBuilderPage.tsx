// Plan builder (the wizard, v2). A screen-per-step wizard per the design record
// (docs/manager-team-suggestions.md): Start (import vs scratch) -> Set your rules (the imported
// 15 first, then an optional market-wide avoid list; scratch mode keeps the full lock/exclude
// picker with its quota, club-cap, and budget guards) -> Review & run. The browser cannot solve
// (the optimizer is PuLP/CBC in Python),
// so the final screen is the command bridge: the wizard emits the exact command to run and the
// result stays in this user-specific page once recorded. The formal platform recommendation
// remains separate on Next GW. The manager_id import
// collects the id now and lands as a P2 job after the deadline -- never faked.
//
// Flow invariant: every screen has exactly one forward and one backward edge, navigation
// NEVER clears state (only the explicitly labelled "Reset rules" does, in place), and the
// review screen ends forward without clearing state, so there is no destructive or dead-end
// exit anywhere in the wizard.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeftRight,
  ArrowRight,
  Ban,
  Check,
  Download,
  LoaderCircle,
  Lock,
  RotateCcw,
  Sparkles,
  UserRoundSearch,
} from "lucide-react";
import { PlanSquadTable, TransferPath } from "@/components/PlanOverview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import type { NextGwPlan, PlayerRecord } from "@/data/types";
import { resolvedPlanKind } from "@/lib/nextGw";
import { clearPlanRequest, writePlanRequest } from "@/lib/planRequest";
import {
  fetchManagerTeam,
  fetchManagerTeamCapture,
  fetchPlanStatus,
  PLAN_SERVER_START_COMMAND,
  solveManagerPlan,
  solvePlan,
  type ManagerTeamPreview,
  type PlanSummary,
} from "@/lib/planServer";
import {
  loadPlanServerToken,
  rememberPlanServerToken,
} from "@/lib/planServerToken";
import { reloadPublishedReadModels } from "@/lib/readModelReload";
import { squadDraftHandoffHref } from "@/lib/squadDraftHandoff";
import { availabilityLabel } from "@/lib/availability";
import { cn } from "@/lib/utils";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      plans: NextGwPlan[];
      runId: string | null;
    };

// Wizard screens: 0 Start, 1 manager import, 2 set rules, 3 review & run, 4 result.
type Step = 0 | 1 | 2 | 3 | 4;
type SelectionMode = "lock" | "exclude";
type ManagerPlayerRule = "flexible" | SelectionMode;
type BuildMode = "scratch" | "manager";

/** The solve card's view of the local plan server (src/fpl/jobs/plan_server.py). */
type SolverStatus =
  | { status: "hosted-static" }
  | { status: "checking" }
  | { status: "offline" }
  | { status: "online" }
  | { status: "runtime-unready" }
  | { status: "worktree-dirty" }
  | { status: "forecast-missing" }
  | { status: "solving"; stage: string | null }
  | { status: "error"; message: string };

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;
const MAX_LOCKS = 5;
const MAX_EXCLUSIONS = 15;
// Current bounded manager search can make at most two first-deadline transfers.
const MANAGER_FIRST_WEEK_TRANSFER_DEPTH = 2;
const PLAYER_PAGE_SIZE = 50;
const DEFAULT_SQUAD_QUOTA: Record<string, number> = { GK: 2, DEF: 5, MID: 5, FWD: 3 };
const THRESHOLDS = [
  { value: "off", label: "Off", flag: null },
  { value: "0.25", label: "25%", flag: "0.25" },
  { value: "0.5", label: "50%", flag: "0.5" },
] as const;
const STEPS = ["Start", "Set your rules", "Review & run", "Your plan"] as const;

// Dev-loop convention (dashboard/README.md): the default GW1-5 artifact the README
// regenerates lives here, and the wizard's own plan output gets a distinct name so it can
// be passed to the next --optimizer-plan publish without clobbering the recorded pair.
// ponytail: a fixed local path the owner's machine guarantees, not a config surface.
const DEV_FORECAST_PATH = "D:\\tmp\\gw1\\dev-latest\\gw1_5_default.jsonl";
const DEV_PLAN_OUTPUT_DIR = "D:\\tmp\\gw1\\dev-latest";
const SOLVED_MANAGER_RESULT_STORAGE_KEY = "fpl-solved-manager-result-v1";
const LEGACY_MANAGER_CAPTURE_STORAGE_KEY = "fpl-solved-manager-capture";
const LEGACY_MANAGER_SUMMARY_STORAGE_KEY = "fpl-solved-manager-summary";

function newManualPlanOutput(): string {
  const token =
    globalThis.crypto?.randomUUID?.().replaceAll("-", "").slice(0, 12) ??
    (Date.now().toString(36) + Math.random().toString(36).slice(2, 8));
  return DEV_PLAN_OUTPUT_DIR + "\\plan_my_rules_" + token + ".json";
}

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

function StepBar({ current }: { current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Wizard steps">
      {STEPS.map((label, index) => {
        const step = index + 1;
        const state = step === current ? "active" : step < current ? "done" : "todo";
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

interface PlayerPickerPagerProps {
  page: number;
  pageCount: number;
  total: number;
  placement: "top" | "bottom";
  onPageChange: (page: number) => void;
}

function PlayerPickerPager({
  page,
  pageCount,
  total,
  placement,
  onPageChange,
}: PlayerPickerPagerProps) {
  const first = total === 0 ? 0 : page * PLAYER_PAGE_SIZE + 1;
  const last = Math.min((page + 1) * PLAYER_PAGE_SIZE, total);
  return (
    <nav
      aria-label={`Player picker pages (${placement})`}
      className={cn(
        "flex items-center justify-between gap-2 rounded-md border bg-background/95 px-2 py-1.5 shadow-sm backdrop-blur",
        placement === "top" ? "sticky top-2 z-10 mb-2" : "mt-3",
      )}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7"
        onClick={() => onPageChange(Math.max(0, page - 1))}
        disabled={page === 0}
      >
        Previous players
      </Button>
      <span
        className="text-center text-xs tabular-nums text-muted-foreground"
        aria-live={placement === "top" ? "polite" : undefined}
      >
        Page {page + 1} of {pageCount}
        {total > 0 && (
          <span className="hidden sm:inline">
            {" "}· showing {first}–{last} of {total}
          </span>
        )}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7"
        onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
        disabled={page >= pageCount - 1}
      >
        Next players
      </Button>
    </nav>
  );
}

function SolverProgress({ stage }: { stage: string | null }) {
  const publishing = stage?.toLowerCase().includes("publishing") ?? false;
  const optimizing = stage?.toLowerCase().includes("solving squad") ?? false;
  const current = publishing ? 2 : optimizing ? 1 : 0;
  const title = publishing
    ? "Publishing your exact plan"
    : optimizing
      ? "Searching for your best legal squad"
      : "Preparing your optimization";
  const detail = publishing
    ? "The squad is solved. We are validating its provenance and refreshing the dashboard read models."
    : optimizing
      ? "PuLP/CBC is comparing legal squads and transfer paths. This is usually the longest step."
      : "Your rules are being validated and the local solver is starting.";
  const steps = ["Prepare run", "Optimize squad", "Publish plan"];

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="mt-3 overflow-hidden rounded-xl border border-sky-200 bg-gradient-to-br from-sky-50 via-background to-indigo-50 p-4 shadow-sm dark:border-sky-900 dark:from-sky-950/40 dark:via-background dark:to-indigo-950/30"
    >
      <div className="flex items-start gap-3">
        <div className="relative flex size-12 shrink-0 items-center justify-center" aria-hidden>
          <span className="absolute inset-0 animate-pulse rounded-full bg-sky-300/30 motion-reduce:animate-none dark:bg-sky-500/20" />
          <span className="absolute inset-1 rounded-full border border-sky-300/70 dark:border-sky-700" />
          <LoaderCircle className="size-7 animate-spin text-sky-600 motion-reduce:animate-none dark:text-sky-300" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">{title}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{detail}</p>
          {stage && !publishing && !optimizing && (
            <p className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
              Server stage: {stage}
            </p>
          )}
        </div>
      </div>
      <ol className="mt-4 grid grid-cols-3 gap-2" aria-label="Optimization stages">
        {steps.map((label, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <li key={label} className="min-w-0">
              <div
                aria-hidden
                className={cn(
                  "mb-1 h-1.5 overflow-hidden rounded-full bg-muted",
                  done && "bg-emerald-500",
                  active && "bg-sky-200 dark:bg-sky-950",
                )}
              >
                {active && (
                  <span className="block h-full w-full animate-pulse rounded-full bg-sky-500 motion-reduce:animate-none" />
                )}
              </div>
              <span
                className={cn(
                  "block truncate text-[10px]",
                  done && "text-emerald-700 dark:text-emerald-300",
                  active ? "font-medium text-sky-700 dark:text-sky-300" : "text-muted-foreground",
                )}
              >
                {done ? "✓ " : ""}{label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
        Usually 1–2 minutes. Keep this tab open; your exact custom plan will open automatically.
        Progress is stage-based because the solver cannot provide a trustworthy completion percentage.
      </p>
    </div>
  );
}

function hashSolvedPlanId(): string | null {
  const query = window.location.hash.split("?", 2)[1];
  if (!query) return null;
  const runId = new URLSearchParams(query).get("run")?.trim();
  return runId || null;
}

function storedSolvedPlanId(): string | null {
  const fromHash = hashSolvedPlanId();
  if (fromHash) return fromHash;
  try {
    return window.localStorage.getItem("fpl-solved-plan");
  } catch {
    return null;
  }
}

function rememberSolvedPlan(runId: string): boolean {
  try {
    window.localStorage.setItem("fpl-solved-plan", runId);
    return true;
  } catch {
    return false;
  }
}

interface StoredManagerResult {
  version: 1;
  optimizerRunId: string;
  managerCaptureId: string;
  summary: PlanSummary | null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function requiredString(value: Record<string, unknown>, key: string): string | null {
  const item = value[key];
  return typeof item === "string" && item.trim() ? item : null;
}

function requiredInteger(
  value: Record<string, unknown>,
  key: string,
  minimum = 0,
): number | null {
  const item = value[key];
  return Number.isSafeInteger(item) && Number(item) >= minimum ? Number(item) : null;
}

function requiredNumber(value: Record<string, unknown>, key: string): number | null {
  const item = value[key];
  return typeof item === "number" && Number.isFinite(item) ? item : null;
}

function parseManagerPlayerRef(value: unknown): { code: number; web_name: string | null } | null {
  const player = objectValue(value);
  if (!player) return null;
  const code = requiredInteger(player, "code", 1);
  const webName = player.web_name;
  if (code == null || (webName !== null && typeof webName !== "string")) return null;
  return { code, web_name: webName };
}

function parseManagerWeek(value: unknown): NonNullable<PlanSummary["manager_weeks"]>[number] | null {
  const week = objectValue(value);
  if (!week || !Array.isArray(week.transfers_in) || !Array.isArray(week.transfers_out)) {
    return null;
  }
  const transfersIn = week.transfers_in.map(parseManagerPlayerRef);
  const transfersOut = week.transfers_out.map(parseManagerPlayerRef);
  const gw = requiredInteger(week, "gw", 1);
  const freeBefore = requiredInteger(week, "free_transfers_before");
  const freeAfter = requiredInteger(week, "free_transfers_after");
  const hitPoints = requiredInteger(week, "hit_points");
  const bankBefore = requiredInteger(week, "bank_before_tenths");
  const bankAfter = requiredInteger(week, "bank_after_tenths");
  if (
    transfersIn.some((player) => player == null) ||
    transfersOut.some((player) => player == null) ||
    gw == null ||
    freeBefore == null ||
    freeAfter == null ||
    hitPoints == null ||
    bankBefore == null ||
    bankAfter == null
  ) {
    return null;
  }
  return {
    gw,
    transfers_in: transfersIn as { code: number; web_name: string | null }[],
    transfers_out: transfersOut as { code: number; web_name: string | null }[],
    free_transfers_before: freeBefore,
    free_transfers_after: freeAfter,
    hit_points: hitPoints,
    bank_before_tenths: bankBefore,
    bank_after_tenths: bankAfter,
  };
}

function parseStoredManagerSummary(value: unknown): PlanSummary | null {
  const summary = objectValue(value);
  if (!summary || !Array.isArray(summary.manager_weeks)) return null;
  const optimizerRunId = requiredString(summary, "optimizer_run_id");
  const decisionSha = requiredString(summary, "decision_sha256");
  const managerCaptureId = requiredString(summary, "manager_capture_id");
  const captain = requiredString(summary, "captain");
  const viceCaptain = requiredString(summary, "vice_captain");
  const gw = requiredInteger(summary, "gw", 1);
  const gwExpectedPoints = requiredNumber(summary, "gw_expected_points");
  const horizonExpectedPoints = requiredNumber(summary, "horizon_expected_points");
  const hitPoints = requiredInteger(summary, "hit_points");
  const squadCost = requiredInteger(summary, "squad_cost_tenths");
  const planningGw = requiredInteger(summary, "manager_planning_gw", 1);
  const existingHits = requiredInteger(summary, "manager_existing_hit_points");
  const initialFreeTransfers = requiredInteger(summary, "manager_initial_free_transfers");
  const bank = requiredInteger(summary, "manager_bank_tenths");
  const sellingValue = requiredInteger(summary, "manager_squad_selling_value_tenths");
  const weeks = summary.manager_weeks.map(parseManagerWeek);
  if (
    !optimizerRunId ||
    !decisionSha ||
    !managerCaptureId ||
    !captain ||
    !viceCaptain ||
    gw == null ||
    gwExpectedPoints == null ||
    horizonExpectedPoints == null ||
    hitPoints == null ||
    squadCost == null ||
    planningGw == null ||
    existingHits == null ||
    initialFreeTransfers == null ||
    bank == null ||
    sellingValue == null ||
    weeks.length === 0 ||
    weeks.some((week) => week == null)
  ) {
    return null;
  }
  const entryName =
    typeof summary.manager_entry_name === "string"
      ? summary.manager_entry_name
      : undefined;
  return {
    optimizer_run_id: optimizerRunId,
    decision_sha256: decisionSha,
    gw,
    gw_expected_points: gwExpectedPoints,
    horizon_expected_points: horizonExpectedPoints,
    hit_points: hitPoints,
    squad_cost_tenths: squadCost,
    captain,
    vice_captain: viceCaptain,
    manager_capture_id: managerCaptureId,
    manager_entry_name: entryName,
    manager_planning_gw: planningGw,
    manager_existing_hit_points: existingHits,
    manager_initial_free_transfers: initialFreeTransfers,
    manager_bank_tenths: bank,
    manager_squad_selling_value_tenths: sellingValue,
    manager_weeks: weeks as NonNullable<PlanSummary["manager_weeks"]>,
  };
}

function managerCaptureFromHash(runId: string): string | null {
  const query = window.location.hash.split("?", 2)[1];
  if (!query) return null;
  const params = new URLSearchParams(query);
  const runs = params.getAll("run");
  const captures = params.getAll("manager_capture_id");
  if (
    runs.length !== 1 ||
    runs[0].trim() !== runId ||
    captures.length !== 1 ||
    !captures[0].trim()
  ) {
    return null;
  }
  return captures[0].trim();
}

function storedManagerResult(runId: string | null): StoredManagerResult | null {
  if (!runId) return null;
  let stored: StoredManagerResult | null = null;
  try {
    const raw = window.localStorage.getItem(SOLVED_MANAGER_RESULT_STORAGE_KEY);
    if (raw) {
      const value = objectValue(JSON.parse(raw));
      const optimizerRunId = value && requiredString(value, "optimizerRunId");
      const managerCaptureId = value && requiredString(value, "managerCaptureId");
      if (value?.version === 1 && optimizerRunId && managerCaptureId) {
        const parsedSummary =
          value.summary == null ? null : parseStoredManagerSummary(value.summary);
        stored = {
          version: 1,
          optimizerRunId,
          managerCaptureId,
          summary:
            parsedSummary?.optimizer_run_id === optimizerRunId &&
            parsedSummary.manager_capture_id === managerCaptureId
              ? parsedSummary
              : null,
        };
      }
    }
  } catch {
    stored = null;
  }
  const hashCapture = managerCaptureFromHash(runId);
  if (hashCapture) {
    return stored?.optimizerRunId === runId && stored.managerCaptureId === hashCapture
      ? stored
      : {
          version: 1,
          optimizerRunId: runId,
          managerCaptureId: hashCapture,
          summary: null,
        };
  }
  return stored?.optimizerRunId === runId ? stored : null;
}

function rememberManagerResult(result: StoredManagerResult | null): boolean {
  try {
    if (result) {
      window.localStorage.setItem(
        SOLVED_MANAGER_RESULT_STORAGE_KEY,
        JSON.stringify(result),
      );
    } else {
      window.localStorage.removeItem(SOLVED_MANAGER_RESULT_STORAGE_KEY);
    }
    window.localStorage.removeItem(LEGACY_MANAGER_CAPTURE_STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_MANAGER_SUMMARY_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

function initialPlanBuilderResult(): {
  runId: string | null;
  manager: StoredManagerResult | null;
} {
  const runId = storedSolvedPlanId();
  return { runId, manager: storedManagerResult(runId) };
}

function planBuilderRunHash(
  runId: string,
  serverToken: string,
  managerCaptureId?: string | null,
): string {
  const params = new URLSearchParams({ run: runId });
  const cleanToken = serverToken.trim();
  if (cleanToken) params.set("server_token", cleanToken);
  if (managerCaptureId) params.set("manager_capture_id", managerCaptureId);
  return "plan-builder?" + params.toString();
}

export function PlanBuilderPage() {
  const hostedStatic = import.meta.env.VITE_HOSTED_STATIC === "true";
  const [initialStoredResult] = useState(initialPlanBuilderResult);
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [rules, setRules] = useState<Rules | null>(null);
  const [resultPlanId, setResultPlanId] = useState<string | null>(
    initialStoredResult.runId,
  );
  const [step, setStep] = useState<Step>(() => (initialStoredResult.runId ? 4 : 0));
  const [manualOutputPath] = useState(newManualPlanOutput);
  const [manualRunId, setManualRunId] = useState("");
  const [manualOpenError, setManualOpenError] = useState<string | null>(null);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const [serverToken, setServerToken] = useState(loadPlanServerToken);
  const [tokenStorageWarning, setTokenStorageWarning] = useState<string | null>(null);
  const [managerId, setManagerId] = useState(() => {
    try {
      return window.localStorage.getItem("fpl-manager-id") ?? "";
    } catch {
      return "";
    }
  });
  const [buildMode, setBuildMode] = useState<BuildMode>(
    initialStoredResult.manager ? "manager" : "scratch",
  );
  const [managerTeam, setManagerTeam] = useState<ManagerTeamPreview | null>(null);
  const [managerLoad, setManagerLoad] = useState<
    "idle" | "loading" | "loaded" | "error"
  >("idle");
  const [managerLoadError, setManagerLoadError] = useState<string | null>(null);
  const [freeTransfersOverride, setFreeTransfersOverride] = useState<number | null>(null);
  const [managerSummary, setManagerSummary] = useState<PlanSummary | null>(
    initialStoredResult.manager?.summary ?? null,
  );
  const [resultManagerCaptureId, setResultManagerCaptureId] = useState<string | null>(
    initialStoredResult.manager?.managerCaptureId ?? null,
  );
  const [locks, setLocks] = useState<PlayerRecord[]>([]);
  const [excludes, setExcludes] = useState<PlayerRecord[]>([]);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("lock");
  const [threshold, setThreshold] = useState<string>("off");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [candidatePage, setCandidatePage] = useState(0);
  const candidateListRef = useRef<HTMLUListElement>(null);
  const focusCandidatePageRef = useRef(false);
  const [copied, setCopied] = useState(false);
  const [solver, setSolver] = useState<SolverStatus>(() =>
    hostedStatic ? { status: "hosted-static" } : { status: "checking" },
  );

  const checkSolver = useCallback(() => {
    if (hostedStatic) {
      setSolver({ status: "hosted-static" });
      return;
    }
    setSolver({ status: "checking" });
    void fetchPlanStatus(serverToken).then((status) => {
      if (!status) {
        setSolver({ status: "offline" });
      } else if (status.runtime?.solver_ready !== true) {
        // A 200 from an older/broken server proves only that HTTP is alive. It must never
        // enable a solve whose PuLP/CBC provenance cannot be resolved.
        setSolver({ status: "runtime-unready" });
      } else if (!status.worktree_clean) {
        setSolver({ status: "worktree-dirty" });
      } else if (!status.forecast_ready) {
        setSolver({ status: "forecast-missing" });
      } else {
        setSolver({ status: "online" });
      }
    });
  }, [hostedStatic, serverToken]);

  // Entering the review screen probes the local plan server once (manual Re-check retries).
  useEffect(() => {
    if (step === 3 && solver.status === "checking") checkSolver();
  }, [step, solver.status, checkSolver]);

  const openExactPublishedRun = (rawRunId: string) => {
    const runId = rawRunId.trim();
    if (!runId) return;
    if (buildMode === "manager") {
      setManualOpenError(
        "A manually published manager run cannot be safely bound to this capture in the browser. Use Solve now so the local Plan Server verifies and returns the exact run/capture pair.",
      );
      return;
    }
    setManualOpenError(null);
    setResultPlanId(runId);
    setManagerSummary(null);
    setResultManagerCaptureId(null);
    setStep(4);
    const rememberedPlan = rememberSolvedPlan(runId);
    const rememberedManager = rememberManagerResult(null);
    setStorageWarning(
      rememberedPlan && rememberedManager
        ? null
        : "Browser storage is unavailable. The exact run id is preserved in this page URL.",
    );
    window.location.hash = planBuilderRunHash(runId, serverToken);
    reloadPublishedReadModels();
  };

  const importManagerTeam = () => {
    if (hostedStatic || !managerValid) return;
    setManagerLoad("loading");
    setManagerLoadError(null);
    void fetchManagerTeam(managerId.trim(), serverToken)
      .then((preview) => {
        setBuildMode("manager");
        setManagerTeam(preview);
        setFreeTransfersOverride(null);
        setLocks([]);
        setExcludes([]);
        setManagerLoad("loaded");
        try {
          localStorage.setItem("fpl-manager-id", String(preview.manager_id));
        } catch {
          // The exact capture remains in component state when browser storage is unavailable.
        }
      })
      .catch((error: unknown) => {
        setManagerTeam(null);
        setManagerLoad("error");
        setManagerLoadError(error instanceof Error ? error.message : String(error));
      });
  };

  useEffect(() => {
    if (
      hostedStatic ||
      step !== 2 ||
      buildMode !== "manager" ||
      managerTeam != null ||
      !resultManagerCaptureId
    ) {
      return;
    }
    let cancelled = false;
    setManagerLoad("loading");
    setManagerLoadError(null);
    void fetchManagerTeamCapture(resultManagerCaptureId, serverToken)
      .then((preview) => {
        if (cancelled) return;
        if (preview.capture_id !== resultManagerCaptureId) {
          throw new Error(
            "Plan server returned a different manager capture than the saved result.",
          );
        }
        setManagerTeam(preview);
        setManagerId(String(preview.manager_id));
        setFreeTransfersOverride(null);
        setManagerLoad("loaded");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setManagerLoad("error");
        setManagerLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [
    buildMode,
    hostedStatic,
    managerTeam,
    resultManagerCaptureId,
    serverToken,
    step,
  ]);

  const solveNow = () => {
    if (hostedStatic) {
      setSolver({ status: "hosted-static" });
      return;
    }
    setSolver({ status: "solving", stage: null });
    const request = {
      locks: locks.map((p) => p.code),
      excludes: excludes.map((p) => p.code),
      minBenchAppearance: thresholdFlag ? Number(thresholdFlag) : null,
    };
    const onStage = (stage: string | null) =>
      setSolver((current) =>
        current.status === "solving"
          ? { ...current, stage: stage ?? current.stage }
          : current,
      );
    const solve =
      buildMode === "manager" && managerTeam
        ? solveManagerPlan(
            {
              ...request,
              captureId: managerTeam.capture_id,
              freeTransfersOverride,
            },
            onStage,
            serverToken,
          )
        : solvePlan(request, onStage, serverToken);
    void solve
      .then((summary) => {
        // The plan server republished the read models. Keep the user inside Plan Builder and
        // reload so the module-level JSON cache refetches the exact returned run id. The URL
        // is the durable fallback when localStorage is denied (private/security modes).
        if (
          buildMode === "manager" &&
          (!managerTeam || summary.manager_capture_id !== managerTeam.capture_id)
        ) {
          throw new Error(
            "Plan server returned a manager result that does not match the imported capture.",
          );
        }
        setResultPlanId(summary.optimizer_run_id);
        const captureId = buildMode === "manager" ? managerTeam?.capture_id ?? null : null;
        setManagerSummary(buildMode === "manager" ? summary : null);
        setResultManagerCaptureId(captureId);
        setStep(4);
        clearPlanRequest();
        const rememberedPlan = rememberSolvedPlan(summary.optimizer_run_id);
        const rememberedManager = rememberManagerResult(
          captureId
            ? {
                version: 1,
                optimizerRunId: summary.optimizer_run_id,
                managerCaptureId: captureId,
                summary,
              }
            : null,
        );
        setStorageWarning(
          rememberedPlan && rememberedManager
            ? null
            : "Browser storage is unavailable. The exact run id is preserved in this page URL.",
        );
        window.location.hash = planBuilderRunHash(
          summary.optimizer_run_id,
          serverToken,
          captureId,
        );
        reloadPublishedReadModels();
      })
      .catch((error: unknown) => {
        setSolver({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
  };

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadNextGw(), loadOptimizerAudit()])
      .then(([playersData, nextGw, audit]) => {
        if (cancelled) return;
        const defaultRun =
          nextGw.plans.find((p) => resolvedPlanKind(p) === "platform_default")
            ?.forecast_run_id ??
          playersData.manifest?.runs.at(-1)?.run_id ??
          playersData.players[0]?.run_id ??
          null;
        const availablePlayers = playersData.players.filter((p) => p.run_id === defaultRun);
        setState({
          status: "ready",
          players: availablePlayers,
          plans: nextGw.plans,
          runId: defaultRun,
        });
        const savedId = storedSolvedPlanId();
        const savedPlan = nextGw.plans.find(
          (plan) =>
            plan.optimizer_run_id === savedId &&
            resolvedPlanKind(plan) === "user_custom",
        );
        if (savedPlan) {
          const locked = new Set(savedPlan.policy.locked_codes);
          const excluded = new Set(savedPlan.policy.excluded_codes);
          setLocks(availablePlayers.filter((player) => locked.has(player.code)));
          setExcludes(availablePlayers.filter((player) => excluded.has(player.code)));
          const savedThreshold = String(savedPlan.policy.min_bench_appearance);
          setThreshold(
            THRESHOLDS.some((option) => option.value === savedThreshold)
              ? savedThreshold
              : "off",
          );
        }
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
  const quota = rules?.squadQuota ?? DEFAULT_SQUAD_QUOTA;
  const maxPerClub = rules?.maxPerClub ?? 3;
  const managerOwnedCodes = useMemo(
    () => new Set(managerTeam?.players.map((player) => player.code) ?? []),
    [managerTeam],
  );
  const managerOwnedExcludedCount = useMemo(
    () => excludes.filter((player) => managerOwnedCodes.has(player.code)).length,
    [excludes, managerOwnedCodes],
  );
  const playerByCode = useMemo(
    () =>
      new Map(
        state.status === "ready"
          ? state.players.map((player) => [player.code, player] as const)
          : [],
      ),
    [state],
  );
  const managerSquadPlayers = useMemo(() => {
    if (!managerTeam) return [];
    return managerTeam.players
      .map((imported) => {
        const player = playerByCode.get(imported.code);
        if (!player) return null;
        return {
          imported,
          player,
          xp: player.fixtures.reduce(
            (sum, fixture) => sum + (fixture.expected_points ?? 0),
            0,
          ),
        };
      })
      .filter((item): item is NonNullable<typeof item> => item != null)
      .sort(
        (a, b) =>
          POSITIONS.indexOf(a.player.position as (typeof POSITIONS)[number]) -
            POSITIONS.indexOf(b.player.position as (typeof POSITIONS)[number]) ||
          a.player.web_name.localeCompare(b.player.web_name),
      );
  }, [managerTeam, playerByCode]);
  const managerUnmappedPlayerCount =
    (managerTeam?.players.length ?? 0) - managerSquadPlayers.length;

  const totals = useMemo(() => {
    if (state.status !== "ready") return null;
    const lockedCost = locks.reduce((sum, p) => sum + (p.now_cost ?? 0), 0);
    const lockedByPos: Record<string, number> = {};
    const lockedByClub: Record<number, number> = {};
    for (const p of locks) {
      lockedByPos[p.position] = (lockedByPos[p.position] ?? 0) + 1;
      lockedByClub[p.team_code] = (lockedByClub[p.team_code] ?? 0) + 1;
    }
    // Cheapest position-quota completion is a lower bound. It excludes every explicit avoid
    // and reports if a position no longer has enough selectable players. The solver remains
    // authoritative for club-cap feasibility.
    let completion = 0;
    let completionPossible = true;
    const lockedCodes = new Set(locks.map((p) => p.code));
    const excludedCodes = new Set(excludes.map((p) => p.code));
    for (const pos of POSITIONS) {
      const remaining = (quota[pos] ?? 0) - (lockedByPos[pos] ?? 0);
      const cheapest = state.players
        .filter(
          (p) =>
            p.position === pos &&
            !lockedCodes.has(p.code) &&
            !excludedCodes.has(p.code) &&
            p.now_cost != null,
        )
        .map((p) => p.now_cost ?? 0)
        .sort((a, b) => a - b)
        .slice(0, Math.max(0, remaining));
      if (cheapest.length < Math.max(0, remaining)) completionPossible = false;
      completion += cheapest.reduce((a, b) => a + b, 0);
    }
    return {
      lockedCost,
      completion,
      completionPossible,
      leftover: budget - lockedCost - completion,
      lockedByPos,
      lockedByClub,
    };
  }, [state, locks, excludes, quota, budget]);

  const lockGuard = (player: PlayerRecord): string | null => {
    if (locks.some((p) => p.code === player.code)) return null;
    if (excludes.some((p) => p.code === player.code)) return "remove exclusion first";
    if (buildMode === "manager" && !managerOwnedCodes.has(player.code)) {
      return "not in imported squad";
    }
    if (locks.length >= MAX_LOCKS) return "max " + MAX_LOCKS + " locks";
    if ((totals?.lockedByPos[player.position] ?? 0) >= (quota[player.position] ?? 0)) {
      return player.position + " quota full";
    }
    if ((totals?.lockedByClub[player.team_code] ?? 0) >= maxPerClub) {
      return "club cap (3)";
    }
    return null;
  };

  const excludeGuard = (player: PlayerRecord): string | null => {
    if (excludes.some((p) => p.code === player.code)) return null;
    if (locks.some((p) => p.code === player.code)) return "remove lock first";
    if (excludes.length >= MAX_EXCLUSIONS) return "max " + MAX_EXCLUSIONS + " exclusions";
    if (
      buildMode === "manager" &&
      managerOwnedCodes.has(player.code) &&
      managerOwnedExcludedCount >= MANAGER_FIRST_WEEK_TRANSFER_DEPTH
    ) {
      return "first-week transfer depth (" + MANAGER_FIRST_WEEK_TRANSFER_DEPTH + ")";
    }
    return null;
  };

  const selectionGuard = (player: PlayerRecord, mode: SelectionMode = selectionMode) =>
    mode === "lock" ? lockGuard(player) : excludeGuard(player);

  const toggleSelection = (
    player: PlayerRecord,
    mode: SelectionMode = selectionMode,
  ) => {
    if (selectionGuard(player, mode)) return;
    if (mode === "lock") {
      setLocks((current) =>
        current.some((p) => p.code === player.code)
          ? current.filter((p) => p.code !== player.code)
          : [...current, player],
      );
    } else {
      setExcludes((current) =>
        current.some((p) => p.code === player.code)
          ? current.filter((p) => p.code !== player.code)
          : [...current, player],
      );
    }
  };

  const managerRule = (player: PlayerRecord): ManagerPlayerRule => {
    if (locks.some((candidate) => candidate.code === player.code)) return "lock";
    if (excludes.some((candidate) => candidate.code === player.code)) return "exclude";
    return "flexible";
  };

  const managerRuleGuard = (
    player: PlayerRecord,
    rule: ManagerPlayerRule,
  ): string | null => {
    const current = managerRule(player);
    if (rule === current || rule === "flexible") return null;
    if (rule === "lock" && locks.length >= MAX_LOCKS) {
      return "maximum keep rules reached";
    }
    if (
      rule === "exclude" &&
      managerOwnedExcludedCount >= MANAGER_FIRST_WEEK_TRANSFER_DEPTH
    ) {
      return `first-week transfer depth (${MANAGER_FIRST_WEEK_TRANSFER_DEPTH})`;
    }
    return null;
  };

  const setManagerRule = (player: PlayerRecord, rule: ManagerPlayerRule) => {
    if (managerRuleGuard(player, rule)) return;
    setLocks((current) => {
      const withoutPlayer = current.filter((candidate) => candidate.code !== player.code);
      return rule === "lock" ? [...withoutPlayer, player] : withoutPlayer;
    });
    setExcludes((current) => {
      const withoutPlayer = current.filter((candidate) => candidate.code !== player.code);
      return rule === "exclude" ? [...withoutPlayer, player] : withoutPlayer;
    });
  };

  const candidates = useMemo(() => {
    if (state.status !== "ready") return [];
    const term = search.trim().toLowerCase();
    return state.players
      .filter((p) => matchesPlayerFilters(p, filters) && p.now_cost != null)
      .filter((p) => buildMode !== "manager" || !managerOwnedCodes.has(p.code))
      .filter((p) => !term || (p.web_name ?? "").toLowerCase().includes(term))
      .map((p) => ({
        player: p,
        xp: p.fixtures.reduce((sum, f) => sum + (f.expected_points ?? 0), 0),
      }))
      .sort(
        (a, b) =>
          b.xp - a.xp ||
          (a.player.now_cost ?? 0) - (b.player.now_cost ?? 0) ||
          a.player.code - b.player.code,
      );
  }, [state, search, filters, buildMode, managerOwnedCodes]);

  const candidatePageCount = Math.max(1, Math.ceil(candidates.length / PLAYER_PAGE_SIZE));
  const visibleCandidates = useMemo(
    () =>
      candidates.slice(
        candidatePage * PLAYER_PAGE_SIZE,
        (candidatePage + 1) * PLAYER_PAGE_SIZE,
      ),
    [candidates, candidatePage],
  );

  // A filter can make the current page disappear. Clamp instead of leaving an empty picker;
  // direct search/filter edits reset to page one below so the matching result is immediately
  // visible. Every eligible priced player remains reachable through the page controls.
  useEffect(() => {
    setCandidatePage((current) => Math.min(current, candidatePageCount - 1));
  }, [candidatePageCount]);

  const changeCandidatePage = (page: number) => {
    const next = Math.min(candidatePageCount - 1, Math.max(0, page));
    if (next === candidatePage) return;
    focusCandidatePageRef.current = true;
    setCandidatePage(next);
  };

  // Paging from the bottom returns the reader to the first selectable result on the new page.
  // Search/filter resets do not move focus unexpectedly because only pager actions set the flag.
  useEffect(() => {
    if (!focusCandidatePageRef.current) return;
    focusCandidatePageRef.current = false;
    const list = candidateListRef.current;
    if (!list) return;
    if (typeof list.scrollIntoView === "function") {
      list.scrollIntoView({ behavior: "auto", block: "start" });
    }
    const firstSelectable = list.querySelector<HTMLButtonElement>("button:not(:disabled)");
    if (firstSelectable) firstSelectable.focus({ preventScroll: true });
    else list.focus({ preventScroll: true });
  }, [candidatePage]);

  const teams = useMemo(() => {
    if (state.status !== "ready") return [] as [number, string][];
    return Array.from(
      new Map(state.players.map((p) => [p.team_code, p.team_short_name] as [number, string])),
    ).sort((a, b) => String(a[1]).localeCompare(String(b[1])));
  }, [state]);

  const resetRules = () => {
    setLocks([]);
    setExcludes([]);
    setSelectionMode("lock");
    setThreshold("off");
    setSearch("");
    setFilters(INITIAL_PLAYER_FILTERS);
    setCandidatePage(0);
  };

  const thresholdFlag = THRESHOLDS.find((t) => t.value === threshold)?.flag ?? null;
  const thresholdLabel = THRESHOLDS.find((t) => t.value === threshold)?.label ?? "Off";
  const isSolving = solver.status === "solving";
  const command = [
    ".\\.venv\\Scripts\\python.exe -m fpl.jobs.optimize_squad",
    DEV_FORECAST_PATH,
    "--risk-lambda 0",
    "--plan-origin user_custom",
    ...(buildMode === "manager" && managerTeam
      ? [
          "--manager-capture " +
            DEV_PLAN_OUTPUT_DIR +
            "\\manager-captures\\" +
            managerTeam.capture_id +
            ".json",
        ]
      : []),
    ...(buildMode === "manager" && freeTransfersOverride != null
      ? ["--free-transfers-override " + freeTransfersOverride]
      : []),
    ...locks.map((p) => `--lock ${p.code}`),
    ...excludes.map((p) => `--exclude ${p.code}`),
    ...(thresholdFlag ? [`--min-bench-appearance ${thresholdFlag}`] : []),
    `--output ${manualOutputPath}`,
  ].join(" ");

  // Reaching (or editing on) review records the request so an interrupted manual solve can
  // resume inside Plan Builder. The formal Next GW suggestion never consumes this state.
  useEffect(() => {
    if (step !== 3) return;
    writePlanRequest({
      version: 2,
      createdAt: new Date().toISOString(),
      threshold,
      thresholdLabel,
      locks: locks.map((p) => ({ code: p.code, web_name: p.web_name, now_cost: p.now_cost })),
      excludes: excludes.map((p) => ({
        code: p.code,
        web_name: p.web_name,
        now_cost: p.now_cost,
      })),
      command,
    });
  }, [step, locks, excludes, threshold, thresholdLabel, command]);

  const resultPlan =
    state.status === "ready" && resultPlanId
      ? state.plans.find(
          (plan) =>
            plan.optimizer_run_id === resultPlanId &&
            resolvedPlanKind(plan) === "user_custom",
        ) ?? null
      : null;

  const managerTouched = managerId.trim() !== "";
  const managerValid =
    /^\d{1,10}$/.test(managerId.trim()) && Number(managerId.trim()) > 0;

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

  const candidatePicker = (mode: SelectionMode) => (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Input
          placeholder={buildMode === "manager" ? "Search players to avoid..." : "Search player..."}
          aria-label={buildMode === "manager" ? "Search avoid-buy player" : "Search player"}
          className="h-8 w-52"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setCandidatePage(0);
          }}
        />
        <span className="text-xs text-muted-foreground">
          {candidates.length === 0
            ? "No eligible priced players match"
            : "Players " +
              (candidatePage * PLAYER_PAGE_SIZE + 1) +
              "–" +
              Math.min((candidatePage + 1) * PLAYER_PAGE_SIZE, candidates.length) +
              " of " +
              candidates.length +
              " by forecast-horizon xP"}
        </span>
      </div>
      <div className="mb-2 rounded-md border bg-background/60 px-2 py-1.5">
        <PlayerFiltersBar
          filters={filters}
          onChange={(nextFilters) => {
            setFilters(nextFilters);
            setCandidatePage(0);
          }}
          teams={teams}
          showFormWindow={false}
        />
      </div>
      <PlayerPickerPager
        page={candidatePage}
        pageCount={candidatePageCount}
        total={candidates.length}
        placement="top"
        onPageChange={changeCandidatePage}
      />
      <ul
        ref={candidateListRef}
        tabIndex={-1}
        aria-label={
          buildMode === "manager"
            ? `Avoid-buy candidates page ${candidatePage + 1}`
            : `Player candidates page ${candidatePage + 1}`
        }
        className="grid scroll-mt-14 gap-1.5 md:grid-cols-1 lg:grid-cols-2"
      >
        {visibleCandidates.map(({ player, xp }) => {
          const locked = locks.some((candidate) => candidate.code === player.code);
          const excluded = excludes.some((candidate) => candidate.code === player.code);
          const blocked = selectionGuard(player, mode);
          const selected = mode === "lock" ? locked : excluded;
          return (
            <li key={player.code}>
              <button
                type="button"
                onClick={() => toggleSelection(player, mode)}
                disabled={!!blocked && !selected}
                aria-pressed={selected}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg border bg-card px-2 py-1.5 text-left text-xs transition-all",
                  locked
                    ? "border-emerald-400/80 bg-emerald-50 ring-1 ring-emerald-400/60 dark:bg-emerald-950/40"
                    : excluded
                      ? "border-red-400/80 bg-red-50 ring-1 ring-red-400/60 dark:bg-red-950/40"
                      : "hover:-translate-y-px hover:border-primary/40 hover:shadow-sm",
                  blocked &&
                    !selected &&
                    "cursor-not-allowed opacity-50 hover:translate-y-0 hover:border-border hover:shadow-none",
                )}
              >
                <PlayerPhoto code={player.code} name={player.web_name} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {player.web_name}
                    {locked && (
                      <Badge className="ml-1 bg-emerald-600 px-1 text-[9px]">locked</Badge>
                    )}
                    {excluded && (
                      <Badge variant="destructive" className="ml-1 px-1 text-[9px]">
                        {buildMode === "manager" ? "avoid" : "excluded"}
                      </Badge>
                    )}
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
                  <span className="block text-[9px] text-muted-foreground">horizon xP</span>
                </span>
                {locked ? (
                  <Lock className="size-3.5 shrink-0 text-emerald-600" />
                ) : excluded ? (
                  <Ban className="size-3.5 shrink-0 text-red-600" />
                ) : blocked ? (
                  <span className="text-[9px] text-muted-foreground">{blocked}</span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
      <PlayerPickerPager
        page={candidatePage}
        pageCount={candidatePageCount}
        total={candidates.length}
        placement="bottom"
        onPageChange={changeCandidatePage}
      />
    </>
  );

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Plan builder</h1>
        <p className="text-xs text-muted-foreground">
          vintage {state.runId?.slice(0, 12)}… · rules from the recorded optimizer artifact ·
          manager-owned transfers and fresh-squad planning
        </p>
      </div>
      <StepBar current={step === 0 || step === 1 ? 1 : step} />

      {step === 0 && (
        <section className="mx-auto grid w-full max-w-3xl gap-4 pt-2 md:grid-cols-2" aria-label="Start">
          <button
            type="button"
            onClick={() => {
              setBuildMode("manager");
              setManualOpenError(null);
              setStep(1);
            }}
            className="group relative overflow-hidden rounded-xl border bg-card p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-lg focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-sky-400 to-indigo-500" />
            <span className="flex size-10 items-center justify-center rounded-lg bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-300">
              <UserRoundSearch className="size-5" />
            </span>
            <p className="mt-3 font-semibold">Import my team</p>
            <Badge variant="outline" className="mt-1.5 border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Ready on local development
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
            onClick={() => {
              setBuildMode("scratch");
              setManagerTeam(null);
              setManagerSummary(null);
              setResultManagerCaptureId(null);
              setManualOpenError(null);
              setStep(2);
            }}
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
              Lock up to {MAX_LOCKS} must-keep players, exclude up to {MAX_EXCLUSIONS} players
              you do not want, and set the bench rotation threshold.
            </p>
            <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary transition-transform group-hover:translate-x-0.5">
              Start configuring <ArrowRight className="size-3" />
            </span>
          </button>
        </section>
      )}

      {step === 1 && (
        <section className="mx-auto w-full max-w-2xl space-y-4 pt-2" aria-label="Import my team">
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold">Import my team</h2>
              <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
                Public API · private local capture
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
              disabled={managerLoad === "loading"}
              onChange={(e) => {
                setManagerId(e.target.value);
                setManagerTeam(null);
                setManagerLoad("idle");
                setManagerLoadError(null);
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
              Manager ID uses FPL's public endpoints. The local service reconstructs purchase and
              selling values from a committed deadline snapshot plus public transfer history and
              fails closed if it cannot reconcile all 15.
            </p>
            {!hostedStatic && (
              <div className="mt-3 rounded-lg border bg-muted/30 p-2.5">
                <label htmlFor="manager-plan-server-token" className="text-xs font-medium">
                  Plan server token <span className="font-normal text-muted-foreground">(LAN only)</span>
                </label>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Input
                    id="manager-plan-server-token"
                    type="password"
                    autoComplete="off"
                    className="h-8 min-w-48 flex-1 font-mono text-xs"
                    placeholder="leave blank on this computer"
                    value={serverToken}
                    disabled={managerLoad === "loading"}
                    onChange={(event) => setServerToken(event.target.value)}
                  />
                  <Button
                    type="button"
                    onClick={importManagerTeam}
                    disabled={!managerValid || managerLoad === "loading"}
                  >
                    {managerLoad === "loading" ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <Download className="size-4" />
                    )}
                    {managerLoad === "loading" ? "Fetching…" : "Get your team"}
                  </Button>
                </div>
              </div>
            )}
            {hostedStatic && (
              <p className="mt-3 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-200">
                Manager import is intentionally local-only. Open this commit with the local plan
                server; the hosted dashboard never receives manager identifiers or squads.
              </p>
            )}
            {managerLoadError && (
              <p role="alert" className="mt-3 text-xs leading-relaxed text-destructive">
                {managerLoadError}
              </p>
            )}
            {managerTeam && (
              <div className="mt-4 rounded-xl border border-emerald-300/70 bg-emerald-50/50 p-3 dark:border-emerald-800 dark:bg-emerald-950/20">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-medium">
                    {managerTeam.entry_name || `Manager #${managerTeam.manager_id}`}
                  </p>
                  <span className="text-[10px] text-muted-foreground">
                    captured {new Date(managerTeam.captured_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Public squad after GW{managerTeam.picks_event} · planning GW
                  {managerTeam.planning_gw} · 15 players reconciled
                </p>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  <div><span className="block text-muted-foreground">Bank</span><strong>{price(managerTeam.bank_tenths)}</strong></div>
                  <div><span className="block text-muted-foreground">Selling value</span><strong>{price(managerTeam.squad_selling_value_tenths)}</strong></div>
                  <div><span className="block text-muted-foreground">Remaining FT</span><strong>{managerTeam.free_transfers_available}</strong></div>
                  <div><span className="block text-muted-foreground">Already-paid hits</span><strong>-{managerTeam.existing_hit_points}</strong></div>
                </div>
                <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
                  This is reconstructed public state, not authenticated FPL “my-team” data.
                  Confirm the remaining free-transfer count before solving; any override is
                  recorded in the optimizer artifact.
                </p>
              </div>
            )}
          </div>
          <div className="rounded-xl border bg-muted/40 p-4">
            <p className="text-xs font-medium text-muted-foreground">What this workflow guarantees</p>
            <ul className="mt-2 space-y-2 text-sm">
              {[
                { icon: Download, text: "Capture your reconstructed 15, bank, purchase bases, and selling values immutably on this machine." },
                { icon: ArrowLeftRight, text: "Start transfers in the first forecast gameweek and charge -4 for each move beyond the effective free transfers." },
                { icon: Lock, text: "Locks mean never sell; excluding an owned player means force that player out at the first actionable deadline." },
              ].map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-start gap-2">
                  <Icon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span className="text-xs leading-relaxed text-muted-foreground">{text}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!managerTeam}
              onClick={() => {
                setBuildMode("manager");
                setStep(2);
              }}
            >
              Set squad rules <ArrowRight className="size-4" />
            </Button>
            <span className="text-[10px] text-muted-foreground">
              The optimizer will start from this exact capture, not a fresh squad.
            </span>
            <Button variant="ghost" onClick={() => setStep(0)}>Back</Button>
          </div>
        </section>
      )}

      {step === 2 && totals && (
        <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
          <section
            aria-label={buildMode === "manager" ? "Imported squad rules" : "Player rules picker"}
            className="rounded-lg border bg-muted/40 p-3"
          >
            {buildMode === "manager" ? (
              <>
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">Your imported squad</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Start with your 15. Leave a player flexible, keep them, or require a
                      first-week sale.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant="outline"
                      className="border-emerald-400 bg-emerald-50 tabular-nums text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                    >
                      <Lock className="size-3" /> Keep {locks.length}/{MAX_LOCKS}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="border-red-400 bg-red-50 tabular-nums text-red-700 dark:bg-red-950/40 dark:text-red-300"
                    >
                      <Ban className="size-3" /> Sell {managerOwnedExcludedCount}/
                      {MANAGER_FIRST_WEEK_TRANSFER_DEPTH}
                    </Badge>
                    {(locks.length > 0 || managerOwnedExcludedCount > 0) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-[11px]"
                        onClick={() => {
                          setLocks([]);
                          setExcludes((current) =>
                            current.filter((player) => !managerOwnedCodes.has(player.code)),
                          );
                        }}
                      >
                        Reset squad rules
                      </Button>
                    )}
                  </div>
                </div>
                {managerUnmappedPlayerCount > 0 && (
                  <p
                    role="alert"
                    className="mb-3 rounded-md border border-red-300 bg-red-50 p-2 text-xs text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-200"
                  >
                    {managerUnmappedPlayerCount} imported player
                    {managerUnmappedPlayerCount === 1 ? " is" : "s are"} absent from the selected
                    dashboard forecast. Refresh the read models before setting transfer rules.
                  </p>
                )}
                <ul
                  aria-label="Imported squad player rules"
                  className="grid gap-2 lg:grid-cols-2"
                >
                  {managerSquadPlayers.map(({ imported, player, xp }) => {
                    const rule = managerRule(player);
                    const lockBlocked = managerRuleGuard(player, "lock");
                    const sellBlocked = managerRuleGuard(player, "exclude");
                    return (
                      <li
                        key={player.code}
                        className={cn(
                          "rounded-lg border bg-card p-2 text-xs transition-colors",
                          rule === "lock" &&
                            "border-emerald-400/80 bg-emerald-50 dark:bg-emerald-950/40",
                          rule === "exclude" &&
                            "border-red-400/80 bg-red-50 dark:bg-red-950/40",
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <PlayerPhoto code={player.code} name={player.web_name} />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{player.web_name}</span>
                            <span className="flex items-center gap-1 text-muted-foreground">
                              <TeamBadge
                                teamCode={player.team_code}
                                shortName={player.team_short_name}
                              />
                              {player.position} · sell {price(imported.selling_price)} · current{" "}
                              {price(imported.now_cost)}
                            </span>
                          </span>
                          <span className="text-right">
                            <span className="block tabular-nums font-medium">{xp.toFixed(1)}</span>
                            <span className="block text-[9px] text-muted-foreground">
                              horizon xP
                            </span>
                          </span>
                        </div>
                        <ToggleGroup
                          type="single"
                          value={rule}
                          onValueChange={(value) =>
                            value && setManagerRule(player, value as ManagerPlayerRule)
                          }
                          variant="outline"
                          size="sm"
                          aria-label={`Rule for ${player.web_name}`}
                          className="mt-2 grid grid-cols-3"
                        >
                          <ToggleGroupItem
                            value="flexible"
                            aria-label={`Flexible ${player.web_name}`}
                          >
                            Flexible
                          </ToggleGroupItem>
                          <ToggleGroupItem
                            value="lock"
                            aria-label={`Keep ${player.web_name}`}
                            title={lockBlocked ?? undefined}
                            disabled={!!lockBlocked && rule !== "lock"}
                          >
                            <Lock className="size-3" /> Keep
                          </ToggleGroupItem>
                          <ToggleGroupItem
                            value="exclude"
                            aria-label={`Sell ${player.web_name}`}
                            title={sellBlocked ?? undefined}
                            disabled={!!sellBlocked && rule !== "exclude"}
                          >
                            <Ban className="size-3" /> Sell
                          </ToggleGroupItem>
                        </ToggleGroup>
                      </li>
                    );
                  })}
                </ul>
                <details className="mt-4 rounded-lg border bg-background/70 p-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    Optional: avoid buying other players
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      {excludes.length - managerOwnedExcludedCount} selected
                    </span>
                  </summary>
                  <p className="mb-3 mt-2 text-xs text-muted-foreground">
                    Search the transfer market only if there are non-owned players the optimizer
                    must never buy. Your imported 15 are managed above.
                  </p>
                  {candidatePicker("exclude")}
                </details>
              </>
            ) : (
              <>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                Player picker — the same search and filters apply to both rules
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <ToggleGroup
                  type="single"
                  value={selectionMode}
                  onValueChange={(value) => value && setSelectionMode(value as SelectionMode)}
                  variant="outline"
                  size="sm"
                  aria-label="Player rule"
                >
                  <ToggleGroupItem value="lock">
                    <Lock className="size-3" /> Lock
                  </ToggleGroupItem>
                  <ToggleGroupItem value="exclude">
                    <Ban className="size-3" /> Exclude
                  </ToggleGroupItem>
                </ToggleGroup>
                <Badge
                  variant="outline"
                  className={cn(
                    "border-emerald-400 bg-emerald-50 tabular-nums text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
                    locks.length === MAX_LOCKS && "bg-emerald-100 dark:bg-emerald-900",
                  )}
                >
                  <Lock className="size-3" /> Locked {locks.length}/{MAX_LOCKS}
                </Badge>
                <Badge
                  variant="outline"
                  className={cn(
                    "border-red-400 bg-red-50 tabular-nums text-red-700 dark:bg-red-950/40 dark:text-red-300",
                    excludes.length === MAX_EXCLUSIONS && "bg-red-100 dark:bg-red-900",
                  )}
                >
                  <Ban className="size-3" /> Excluded {excludes.length}/{MAX_EXCLUSIONS}
                </Badge>
                {(locks.length > 0 || excludes.length > 0) && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[11px]"
                    onClick={() => {
                      setLocks([]);
                      setExcludes([]);
                    }}
                  >
                    Clear selections
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
                onChange={(e) => {
                  setSearch(e.target.value);
                  setCandidatePage(0);
                }}
              />
              <span className="text-xs text-muted-foreground">
                {candidates.length === 0
                  ? "No eligible priced players match"
                  : "Players " +
                    (candidatePage * PLAYER_PAGE_SIZE + 1) +
                    "–" +
                    Math.min((candidatePage + 1) * PLAYER_PAGE_SIZE, candidates.length) +
                    " of " +
                    candidates.length +
                    " by forecast-horizon xP"}
              </span>
            </div>
            <div className="mb-2 rounded-md border bg-background/60 px-2 py-1.5">
              <PlayerFiltersBar
                filters={filters}
                onChange={(nextFilters) => {
                  setFilters(nextFilters);
                  setCandidatePage(0);
                }}
                teams={teams}
                showFormWindow={false}
              />
            </div>
            <PlayerPickerPager
              page={candidatePage}
              pageCount={candidatePageCount}
              total={candidates.length}
              placement="top"
              onPageChange={changeCandidatePage}
            />
            <ul
              ref={candidateListRef}
              tabIndex={-1}
              aria-label={`Player candidates page ${candidatePage + 1}`}
              className="grid scroll-mt-14 gap-1.5 md:grid-cols-1 lg:grid-cols-2"
            >
              {visibleCandidates.map(({ player, xp }) => {
                const locked = locks.some((p) => p.code === player.code);
                const excluded = excludes.some((p) => p.code === player.code);
                const blocked = selectionGuard(player);
                const selected = selectionMode === "lock" ? locked : excluded;
                return (
                  <li key={player.code}>
                    <button
                      type="button"
                      onClick={() => toggleSelection(player)}
                      disabled={!!blocked && !selected}
                      aria-pressed={selected}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg border bg-card px-2 py-1.5 text-left text-xs transition-all",
                        locked
                          ? "border-emerald-400/80 bg-emerald-50 ring-1 ring-emerald-400/60 dark:bg-emerald-950/40"
                          : excluded
                            ? "border-red-400/80 bg-red-50 ring-1 ring-red-400/60 dark:bg-red-950/40"
                            : "hover:-translate-y-px hover:border-primary/40 hover:shadow-sm",
                        blocked &&
                          !selected &&
                          "cursor-not-allowed opacity-50 hover:translate-y-0 hover:border-border hover:shadow-none",
                      )}
                    >
                      <PlayerPhoto code={player.code} name={player.web_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">
                          {player.web_name}
                          {locked && (
                            <Badge className="ml-1 bg-emerald-600 px-1 text-[9px]">locked</Badge>
                          )}
                          {excluded && (
                            <Badge variant="destructive" className="ml-1 px-1 text-[9px]">
                              excluded
                            </Badge>
                          )}
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
                        <span className="block text-[9px] text-muted-foreground">horizon xP</span>
                      </span>
                      {locked ? (
                        <Lock className="size-3.5 shrink-0 text-emerald-600" />
                      ) : excluded ? (
                        <Ban className="size-3.5 shrink-0 text-red-600" />
                      ) : blocked ? (
                        <span className="text-[9px] text-muted-foreground">{blocked}</span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
            <PlayerPickerPager
              page={candidatePage}
              pageCount={candidatePageCount}
              total={candidates.length}
              placement="bottom"
              onPageChange={changeCandidatePage}
            />
              </>
            )}
          </section>

          <section aria-label="Your rules" className="flex flex-col gap-3">
            <div className="rounded-xl border bg-card p-3 shadow-sm">
              <p className="mb-2 text-xs font-medium text-muted-foreground">Your rules</p>
              {buildMode === "manager" && (
                <>
                  <p className="text-sm">
                    Kept:{" "}
                    <span className="font-medium tabular-nums">
                      {locks.length} of {MAX_LOCKS}
                    </span>
                  </p>
                  <p className="mt-1 text-sm">
                    Required sales:{" "}
                    <span className="font-medium tabular-nums">
                      {managerOwnedExcludedCount} of {MANAGER_FIRST_WEEK_TRANSFER_DEPTH}
                    </span>
                  </p>
                  <p className="mt-1 text-sm">
                    Avoid buying:{" "}
                    <span className="font-medium tabular-nums">
                      {excludes.length - managerOwnedExcludedCount} selected
                    </span>
                  </p>
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Flexible players may be kept or sold. Required sales happen at the first
                    actionable deadline; avoid-buy rules apply only to players outside your squad.
                  </p>
                </>
              )}
              {buildMode === "scratch" && (
                <>
              <p className="text-sm">
                Locks:{" "}
                <span className="font-medium tabular-nums">
                  {locks.length
                    ? `${locks.length} of ${MAX_LOCKS}`
                    : "none — the optimizer picks all 15"}
                </span>
              </p>
              <p className="mt-1 text-sm">
                Exclusions:{" "}
                <span className="font-medium tabular-nums">
                  {excludes.length ? excludes.length + " of " + MAX_EXCLUSIONS : "none"}
                </span>
              </p>
                </>
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
              {buildMode === "scratch" ? (
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
                    cheapest position fill {price(totals.completion)}
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
                  {!totals.completionPossible
                    ? "not enough non-excluded players to complete every position"
                    : totals.leftover < 0
                    ? `over budget by ${price(-totals.leftover)} — unlock a player`
                    : `headroom ${price(totals.leftover)}${totals.lockedCost / budget > 0.9 ? " (warning: >90% committed)" : ""}`}
                </div>
              </div>
              ) : managerTeam ? (
                <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50/50 p-3 dark:border-sky-900 dark:bg-sky-950/20">
                  <p className="text-xs font-medium">Imported manager transfer state</p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                    <span>Cash bank <strong className="block">{price(managerTeam.bank_tenths)}</strong></span>
                    <span>Selling value <strong className="block">{price(managerTeam.squad_selling_value_tenths)}</strong></span>
                  </div>
                  <label htmlFor="free-transfers-override" className="mt-3 block text-xs font-medium">
                    Remaining free transfers
                  </label>
                  <select
                    id="free-transfers-override"
                    className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-xs"
                    value={freeTransfersOverride == null ? "capture" : String(freeTransfersOverride)}
                    onChange={(event) =>
                      setFreeTransfersOverride(
                        event.target.value === "capture" ? null : Number(event.target.value),
                      )
                    }
                  >
                    <option value="capture">
                      Use reconstructed value ({managerTeam.free_transfers_available})
                    </option>
                    {[0, 1, 2, 3, 4, 5].map((value) => (
                      <option key={value} value={value}>Override: {value}</option>
                    ))}
                  </select>
                  <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
                    Already-paid hits: -{managerTeam.existing_hit_points} (sunk; never charged
                    twice). New suggestions beyond the effective free transfers cost -4 each.
                  </p>
                </div>
              ) : buildMode === "manager" ? (
                <div
                  role={managerLoad === "error" ? "alert" : "status"}
                  className={cn(
                    "mt-3 rounded-lg border p-3 text-xs",
                    managerLoad === "error"
                      ? "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-200"
                      : "border-sky-200 bg-sky-50/50 text-sky-800 dark:border-sky-900 dark:bg-sky-950/20 dark:text-sky-200",
                  )}
                >
                  {managerLoad === "loading"
                    ? "Reloading the exact saved manager capture..."
                    : managerLoadError ??
                      "The exact manager capture must be loaded before this plan can be edited."}
                  {managerLoad === "error" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="mt-2"
                      onClick={() => setStep(1)}
                    >
                      Return to manager import
                    </Button>
                  )}
                </div>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => setStep(3)}
                disabled={
                  (buildMode === "scratch" &&
                    (totals.leftover < 0 || !totals.completionPossible)) ||
                  (buildMode === "manager" &&
                    (managerTeam == null ||
                      managerOwnedExcludedCount >
                        MANAGER_FIRST_WEEK_TRANSFER_DEPTH ||
                      managerUnmappedPlayerCount > 0))
                }
              >
                Next: Review & run <ArrowRight className="size-4" />
              </Button>
              <Button variant="outline" size="sm" onClick={resetRules}>
                <RotateCcw className="size-3.5" /> Reset rules
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStep(0)}>
                Back to start
              </Button>
            </div>
          </section>
        </div>
      )}

      {step === 3 && totals && (
        <section className="mx-auto grid w-full max-w-2xl gap-4 pt-2" aria-label="Review and run">
          <div className="rounded-xl border bg-card p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">Review your rules</p>
              <span className="text-xs tabular-nums text-muted-foreground">
                {buildMode === "manager" && managerTeam
                  ? `GW${managerTeam.planning_gw} · bank ${price(managerTeam.bank_tenths)} · FT ${freeTransfersOverride ?? managerTeam.free_transfers_available}`
                  : `threshold ${thresholdLabel} · budget ${price(budget)}`}
              </span>
            </div>
            <p className="mt-3 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {buildMode === "manager" ? "Keep rules" : "Locked players"}
            </p>
            {locks.length ? (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Locked players">
                {locks.map((p) => (
                  <li
                    key={p.code}
                    className="flex items-center gap-1.5 rounded-full border border-emerald-300/70 bg-emerald-50 py-0.5 pl-1 pr-1.5 text-xs dark:border-emerald-700 dark:bg-emerald-950/40"
                  >
                    <PlayerPhoto code={p.code} name={p.web_name} size="sm" />
                    <span className="font-medium">{p.web_name}</span>
                    <span className="text-muted-foreground">{price(p.now_cost)}</span>
                    <button
                      type="button"
                      aria-label={`Unlock ${p.web_name}`}
                      disabled={isSolving}
                      onClick={() => setLocks((current) => current.filter((x) => x.code !== p.code))}
                      className="rounded-full px-1 text-muted-foreground transition-colors hover:bg-emerald-100 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-emerald-900/60"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                {buildMode === "manager"
                  ? "No keep rules — every imported player remains flexible."
                  : "No locks — the optimizer picks all 15."}
              </p>
            )}
            <p className="mt-3 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {buildMode === "manager" ? "Sales and avoid-buy rules" : "Excluded players"}
            </p>
            {excludes.length ? (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Excluded players">
                {excludes.map((p) => (
                  <li
                    key={p.code}
                    className="flex items-center gap-1.5 rounded-full border border-red-300/70 bg-red-50 py-0.5 pl-1 pr-1.5 text-xs dark:border-red-700 dark:bg-red-950/40"
                  >
                    <PlayerPhoto code={p.code} name={p.web_name} size="sm" />
                    <span className="font-medium">{p.web_name}</span>
                    <span className="text-muted-foreground">{price(p.now_cost)}</span>
                    {buildMode === "manager" && (
                      <Badge variant="outline" className="h-4 px-1 text-[9px]">
                        {managerOwnedCodes.has(p.code) ? "sell" : "avoid"}
                      </Badge>
                    )}
                    <button
                      type="button"
                      aria-label={`Remove exclusion ${p.web_name}`}
                      disabled={isSolving}
                      onClick={() =>
                        setExcludes((current) => current.filter((x) => x.code !== p.code))
                      }
                      className="rounded-full px-1 text-muted-foreground transition-colors hover:bg-red-100 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-red-900/60"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                {buildMode === "manager"
                  ? "No required sales or avoid-buy rules."
                  : "No excluded players."}
              </p>
            )}
            {buildMode === "scratch" ? (
            <div
              className={cn(
                "mt-3 text-sm tabular-nums",
                totals.leftover < 0 ? "font-medium text-destructive" : "text-muted-foreground",
              )}
            >
              {totals.leftover < 0
                ? `over budget by ${price(-totals.leftover)} — go back and unlock a player`
                : `headroom ${price(totals.leftover)} after the cheapest position fill`}
            </div>
            ) : managerTeam ? (
              <div className="mt-3 rounded-lg border bg-muted/30 p-3 text-xs">
                <p>
                  Imported public squad: <strong>{managerTeam.entry_name || `#${managerTeam.manager_id}`}</strong>
                  {" "}· selling value {price(managerTeam.squad_selling_value_tenths)}
                  {" "}· cash {price(managerTeam.bank_tenths)}
                </p>
                <p className="mt-1 text-muted-foreground">
                  Effective remaining FT: {freeTransfersOverride ?? managerTeam.free_transfers_available}
                  {freeTransfersOverride == null ? " (reconstructed)" : " (user override)"}
                  {" "}· already-paid hits -{managerTeam.existing_hit_points}
                </p>
              </div>
            ) : null}
            <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
              {buildMode === "manager"
                ? "Captured purchase/selling values govern the first move; future prices remain frozen. Existing hits are sunk and new excess transfers cost -4. Development-only output."
                : "Frozen prices at the deadline; availability is a reported overlay for the next gameweek only. Development-only output."}
            </p>
          </div>

          {hostedStatic ? (
            <div
              className="rounded-xl border border-sky-200 bg-sky-50/60 p-5 shadow-sm dark:border-sky-900 dark:bg-sky-950/20"
              aria-label="Hosted Plan Builder boundary"
            >
              <Badge variant="outline" className="border-sky-300 text-sky-700 dark:border-sky-800 dark:text-sky-300">
                Hosted read-only
              </Badge>
              <h3 className="mt-3 font-semibold">Optimization stays on your trusted machine</h3>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                This public dashboard is read-only for optimization. It never contacts or exposes
                the local Python/PuLP plan server. Use Squad draft for browser-only planning, or
                open this same commit on a trusted machine to solve and publish an exact custom
                plan.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild>
                  <a href="#squad-draft">Open Squad draft</a>
                </Button>
                <Button variant="outline" onClick={() => setStep(2)}>
                  Back to rules
                </Button>
                <Button variant="ghost" asChild>
                  <a href="#next-gw">View platform suggestion</a>
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div
                className="rounded-xl border bg-card p-4 shadow-sm"
                aria-label="Solve"
                aria-busy={isSolving}
              >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">Solve it now</p>
              {solver.status === "online" && (
                <Badge
                  variant="outline"
                  className="border-emerald-300 bg-emerald-50 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                >
                  <span className="inline-block size-1.5 rounded-full bg-emerald-500" /> plan server online
                </Badge>
              )}
              {solver.status === "runtime-unready" && (
                <Badge
                  variant="outline"
                  className="border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                >
                  solver runtime unavailable
                </Badge>
              )}
              {solver.status === "worktree-dirty" && (
                <Badge
                  variant="outline"
                  className="border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                >
                  commit required
                </Badge>
              )}
              {solver.status === "forecast-missing" && (
                <Badge
                  variant="outline"
                  className="border-amber-300 bg-amber-50 text-[10px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                >
                  forecast unavailable
                </Badge>
              )}
              {solver.status === "solving" && (
                <Badge variant="outline" className="text-[10px]">
                  <span className="inline-block size-1.5 animate-pulse rounded-full bg-sky-500" /> running
                </Badge>
              )}
            </div>
            <p className="mt-2 text-sm leading-relaxed">
              Runs the <span className="font-medium">real optimizer</span> on this machine with
              {buildMode === "manager"
                ? " your imported squad, selling values, confirmed free transfers, locks, exclusions, and threshold. It returns who to sell and buy, including new -4 hits."
                : " your locks, exclusions, and threshold, then republishes the read models."}
              {" "}Your exact scenario remains here; it never replaces the platform suggestion.
            </p>
            <div className="mt-3 rounded-lg border bg-muted/30 p-2.5">
              <label htmlFor="plan-server-token" className="text-xs font-medium">
                Plan server token{" "}
                <span className="font-normal text-muted-foreground">(LAN only)</span>
              </label>
              <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                Leave blank on this computer. A phone or other LAN device must use the
                per-launch token printed by the plan server.
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Input
                  id="plan-server-token"
                  type="password"
                  autoComplete="off"
                  className="h-8 min-w-48 flex-1 font-mono text-xs"
                  placeholder="per-launch token"
                  value={serverToken}
                  disabled={isSolving}
                  onChange={(event) => setServerToken(event.target.value)}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={isSolving}
                  onClick={() => {
                    const remembered = rememberPlanServerToken(serverToken);
                    setTokenStorageWarning(
                      remembered
                        ? null
                        : "Token storage is unavailable; this tab will keep using the entered token.",
                    );
                    checkSolver();
                  }}
                >
                  Use token &amp; re-check
                </Button>
              </div>
              {tokenStorageWarning && (
                <p className="mt-1 text-[10px] text-amber-700 dark:text-amber-300">
                  {tokenStorageWarning}
                </p>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                onClick={solveNow}
                disabled={
                  solver.status !== "online" ||
                  (buildMode === "scratch" &&
                    (totals.leftover < 0 || !totals.completionPossible)) ||
                  (buildMode === "manager" && managerTeam == null)
                }
              >
                <Sparkles className="size-4" />
                {solver.status === "solving" ? "Solving…" : "Solve now with my rules"}
              </Button>
              {(solver.status === "offline" ||
                solver.status === "runtime-unready" ||
                solver.status === "worktree-dirty" ||
                solver.status === "forecast-missing") && (
                <Button variant="ghost" size="sm" onClick={checkSolver}>
                  Re-check
                </Button>
              )}
            </div>
            {solver.status === "solving" && (
              <SolverProgress stage={solver.stage} />
            )}
            {solver.status === "offline" && (
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Offline — start it from the repository root with{" "}
                <code className="rounded bg-muted px-1 font-mono text-[10px]">
                  {PLAN_SERVER_START_COMMAND}
                </code>{" "}
                (see dashboard/README.md), or run the copied command below by hand.
              </p>
            )}
            {solver.status === "runtime-unready" && (
              <p role="alert" className="mt-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
                The plan server answered, but its PuLP/CBC solver runtime is not ready. Stop it,
                then restart it from the repository root with{" "}
                <code className="rounded bg-muted px-1 font-mono text-[10px]">
                  {PLAN_SERVER_START_COMMAND}
                </code>
                . Solve stays disabled until the restarted server reports a verified runtime.
              </p>
            )}
            {solver.status === "worktree-dirty" && (
              <p role="alert" className="mt-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
                The Git worktree has pending changes. Commit them, then re-check. The optimizer
                refuses to publish a decision that cannot be pinned to an exact commit.
              </p>
            )}
            {solver.status === "forecast-missing" && (
              <p role="alert" className="mt-2 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
                The required forecast artifact is missing. Regenerate it using the exact
                development workflow in dashboard/README.md, then re-check.
              </p>
            )}
            {solver.status === "error" && (
              <p role="alert" className="mt-2 text-xs leading-relaxed text-destructive">
                {solver.message} — the server console carries the full detail; the copied command
                below remains the manual fallback.
              </p>
            )}
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
            <p className="px-3 py-2 text-[10px] leading-relaxed text-muted-foreground">
              The primary button sends these rules to the local Python optimizer and publishes
              your exact result automatically. This transparent manual fallback uses the unique output{" "}
              <span className="font-mono">{manualOutputPath}</span>, so it cannot overwrite
              another custom scenario. After it finishes, re-publish the read models with that
              exact file as <span className="font-mono">--optimizer-plan</span>. The platform
              Next GW page intentionally remains unchanged.
            </p>
            <div
              className="mx-3 mb-3 rounded-lg border bg-muted/30 p-3"
              aria-label="Open manually published plan"
            >
              {buildMode === "manager" ? (
                <p role="alert" className="text-xs leading-relaxed text-amber-700 dark:text-amber-300">
                  Manual manager-result opening is unavailable: the browser cannot prove that a
                  pasted run id was produced from this exact private capture. Use Solve now so the
                  Plan Server verifies the run/capture pair and enables both Squad Draft handoffs.
                </p>
              ) : (
                <>
                  <label htmlFor="manual-run-id" className="text-xs font-medium">
                    Published optimizer run id
                  </label>
                  <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                    Copy <span className="font-mono">optimizer_run_id</span> from the generated plan
                    after publishing. Opening it records only that exact id; a missing or non-custom
                    run fails visibly and never falls back to a platform squad.
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Input
                      id="manual-run-id"
                      aria-label="Published optimizer run id"
                      className="h-8 min-w-56 flex-1 font-mono text-xs"
                      placeholder="paste optimizer_run_id"
                      value={manualRunId}
                      disabled={isSolving}
                      onChange={(event) => {
                        setManualRunId(event.target.value);
                        setManualOpenError(null);
                      }}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={isSolving || !manualRunId.trim()}
                      onClick={() => openExactPublishedRun(manualRunId)}
                    >
                      Open exact custom plan
                    </Button>
                  </div>
                  {manualOpenError && (
                    <p role="alert" className="mt-2 text-xs text-destructive">
                      {manualOpenError}
                    </p>
                  )}
                </>
              )}
            </div>
            <div className="flex items-center gap-2 px-3 pb-3">
              <Button
                size="sm"
                variant="outline"
                disabled={isSolving}
                onClick={() => setStep(2)}
              >
                Back to rules
              </Button>
              <Button size="sm" asChild>
                <a href="#next-gw">
                  View platform suggestion <ArrowRight className="size-3.5" />
                </a>
              </Button>
            </div>
              </div>
            </>
          )}
        </section>
      )}

      {step === 4 && (
        <section className="space-y-4" aria-label="Your plan result">
          {!resultPlan ? (
            <div className="mx-auto max-w-2xl rounded-xl border border-red-300 bg-red-50 p-5 dark:border-red-800 dark:bg-red-950/30">
              <h2 className="font-semibold">Your solved plan is not in the published read model</h2>
              <p role="alert" className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Expected optimizer run{" "}
                <span className="font-mono text-foreground">{resultPlanId ?? "unknown"}</span>.
                Plan Builder will not silently show the platform squad or a different custom run.
                Re-publish that exact artifact, then reload.
              </p>
              {storageWarning && (
                <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                  {storageWarning}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={reloadPublishedReadModels}>Reload read models</Button>
                <Button variant="outline" onClick={() => setStep(2)}>
                  Edit rules
                </Button>
                <Button variant="ghost" asChild>
                  <a href="#next-gw">View platform suggestion</a>
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <h2 className="text-lg font-semibold">
                    Your plan — GW{resultPlan.gw_from}
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    Your rule-specific scenario. It is deliberately separate from the formal
                    platform suggestion.
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs">
                  <Badge
                    variant="outline"
                    className="border-emerald-400 bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                  >
                    <Lock className="size-3" /> {resultPlan.policy.locked_codes.length} locked
                  </Badge>
                  <Badge
                    variant="outline"
                    className="border-red-400 bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"
                  >
                    <Ban className="size-3" /> {resultPlan.policy.excluded_codes.length} excluded
                  </Badge>
                  <Badge variant="outline">
                    bench floor{" "}
                    {Math.round(resultPlan.policy.min_bench_appearance * 100)}%
                  </Badge>
                </div>
              </div>
              {storageWarning && (
                <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
                  {storageWarning}
                </p>
              )}

              {(resultPlan.policy.locked_codes.length > 0 ||
                resultPlan.policy.excluded_codes.length > 0) && (
                <div className="flex flex-wrap gap-2 text-xs">
                  {resultPlan.policy.locked_codes.map((code) => (
                    <span
                      key={"lock-" + code}
                      className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-1 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200"
                    >
                      locked ·{" "}
                      {state.players.find((player) => player.code === code)?.web_name ?? code}
                    </span>
                  ))}
                  {resultPlan.policy.excluded_codes.map((code) => (
                    <span
                      key={"exclude-" + code}
                      className="rounded-full border border-red-300 bg-red-50 px-2 py-1 text-red-800 dark:border-red-700 dark:bg-red-950/40 dark:text-red-200"
                    >
                      excluded ·{" "}
                      {state.players.find((player) => player.code === code)?.web_name ?? code}
                    </span>
                  ))}
                </div>
              )}

              {managerSummary?.optimizer_run_id === resultPlan.optimizer_run_id &&
                managerSummary.manager_weeks && (
                  <section className="rounded-xl border border-sky-200 bg-sky-50/40 p-4 dark:border-sky-900 dark:bg-sky-950/20" aria-label="Manager transfer recommendations">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <h3 className="font-semibold">Your transfer suggestion</h3>
                        <p className="text-xs text-muted-foreground">
                          {managerSummary.manager_entry_name || "Imported manager"} · captured
                          state, not a fresh 100.0 squad
                        </p>
                      </div>
                      <div className="flex gap-1.5 text-xs">
                        <Badge variant="outline">
                          sunk hits -{managerSummary.manager_existing_hit_points ?? 0}
                        </Badge>
                        <Badge
                          variant="outline"
                          className={cn(
                            (managerSummary.hit_points ?? 0) > 0 &&
                              "border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300",
                          )}
                        >
                          new hits -{managerSummary.hit_points}
                        </Badge>
                      </div>
                    </div>
                    <ol className="mt-3 space-y-2">
                      {managerSummary.manager_weeks.map((week) => (
                        <li key={week.gw} className="rounded-lg border bg-background/80 p-3 text-xs">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <strong>GW{week.gw}</strong>
                            <span className="text-muted-foreground">
                              FT {week.free_transfers_before} → {week.free_transfers_after} ·
                              bank {price(week.bank_before_tenths)} → {price(week.bank_after_tenths)}
                              {week.hit_points > 0 ? ` · hit -${week.hit_points}` : ""}
                            </span>
                          </div>
                          {week.transfers_in.length === 0 ? (
                            <p className="mt-1 font-medium text-emerald-700 dark:text-emerald-300">
                              HOLD — bank the free transfer
                            </p>
                          ) : (
                            <div className="mt-2 grid gap-1 sm:grid-cols-2">
                              <p>
                                <span className="font-medium text-red-700 dark:text-red-300">OUT</span>
                                {" "}
                                {week.transfers_out.map((player) => player.web_name ?? player.code).join(", ")}
                              </p>
                              <p>
                                <span className="font-medium text-emerald-700 dark:text-emerald-300">IN</span>
                                {" "}
                                {week.transfers_in.map((player) => player.web_name ?? player.code).join(", ")}
                              </p>
                            </div>
                          )}
                        </li>
                      ))}
                    </ol>
                    <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">
                      Already-paid hits are shown for context and are never deducted twice. Future
                      prices are frozen at this capture/forecast vintage.
                    </p>
                  </section>
                )}

              <PlanSquadTable plan={resultPlan} />
              <TransferPath weeks={resultPlan.weeks} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  optimizer run {resultPlan.optimizer_run_id.slice(0, 12)}… · development-only ·
                  frozen deadline prices
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" onClick={() => setStep(2)}>
                    Edit and solve again
                  </Button>
                  <Button asChild>
                    <a
                      href={
                        resultManagerCaptureId
                          ? squadDraftHandoffHref(resultPlan.optimizer_run_id, {
                              source: "optimized",
                            })
                          : squadDraftHandoffHref(resultPlan.optimizer_run_id)
                      }
                    >
                      {resultManagerCaptureId
                        ? "Forward suggested team to Squad Draft"
                        : "Forward team to Squad Draft"}
                    </a>
                  </Button>
                  {resultManagerCaptureId && (
                    <Button asChild variant="outline">
                      <a
                        href={squadDraftHandoffHref(resultPlan.optimizer_run_id, {
                          source: "manager_current",
                          managerCaptureId: resultManagerCaptureId,
                          serverToken,
                        })}
                      >
                        Use captured current team in Squad Draft
                      </a>
                    </Button>
                  )}
                  <Button asChild variant="outline">
                    <a href="#next-gw">View platform suggestion</a>
                  </Button>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
