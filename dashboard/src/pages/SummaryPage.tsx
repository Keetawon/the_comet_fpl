// Summary landing page: what is interesting RIGHT NOW, derived client-side from the same
// read models the exploratory pages use (one SELECTED vintage -- the default architecture
// an optimizer plan references). Sections: next gameweek, optimizer squad summaries,
// availability watch (the reported injury/doubt overlay), players to watch (GW1 and
// horizon xP), and teams to watch (schedule ease extremes with recent form and the next
// fixtures). Every number links back to a page that exposes its primitives; headline EV
// is never compared across architectures.

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { FixtureTicker } from "@/components/FixtureTicker";
import { VintageSelect } from "@/components/VintageSelect";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadPlayers,
  loadSummary,
} from "@/data/load";
import type {
  NextGwPlan,
  PlayerRecord,
  SummaryData,
  TeamRecord,
} from "@/data/types";
import { availabilityLabel } from "@/lib/availability";
import { chipBucket, chipMetric } from "@/lib/fixtureChips";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import {
  planDisplayLabel,
  platformPlans,
  resolvedPlanKind,
} from "@/lib/nextGw";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      summary: SummaryData;
      players: PlayerRecord[];
      teams: TeamRecord[];
      plans: NextGwPlan[];
      runs: { run_id: string; season: string; gw_from: number; gw_to: number }[];
      defaultRunId: string;
    };

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

/** GW1 (first-horizon-gameweek) xP for a player: both legs of a double gameweek count. */
function gwXp(player: PlayerRecord, gw: number): number | null {
  const values = player.fixtures
    .filter((f) => f.gw === gw)
    .map((f) => f.expected_points)
    .filter((v): v is number => v != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
}

function horizonXpSum(player: PlayerRecord, gwFrom: number, gwTo: number): number | null {
  const values = player.fixtures
    .filter((f) => f.gw >= gwFrom && f.gw <= gwTo)
    .map((f) => f.expected_points)
    .filter((v): v is number => v != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
}

function savedCustomPlanId(): string | null {
  try {
    return window.localStorage.getItem("fpl-solved-plan");
  } catch {
    return null;
  }
}

function Card({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border bg-card p-3 ${className ?? ""}`}>
      <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>
      {children}
    </section>
  );
}

function PlayerLine({ player, value, valueLabel }: { player: PlayerRecord; value: number | null; valueLabel?: string }) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="flex min-w-0 items-center gap-1.5">
        <PlayerPhoto code={player.code} name={player.web_name} />
        <span className="min-w-0 truncate">
          <span className="font-medium">{player.web_name}</span>
          <span className="ml-1 text-xs text-muted-foreground">
            {player.position} · {player.team_short_name} · {price(player.now_cost)}
          </span>
        </span>
      </span>
      <span className="tabular-nums text-sm" title={valueLabel}>
        {fmt(value)}
      </span>
    </li>
  );
}

export function SummaryPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadSummary(), loadPlayers(), loadFixtureMatrix(), loadNextGw()])
      .then(([summary, playersData, teamsData, nextGw]) => {
        if (cancelled) return;
        const seen = new Map<string, { run_id: string; season: string; gw_from: number; gw_to: number }>();
        for (const p of playersData.players) {
          const gws = p.fixtures.map((f) => f.gw);
          if (!gws.length) continue;
          const from = Math.min(...gws);
          const to = Math.max(...gws);
          const existing = seen.get(p.run_id);
          if (!existing) seen.set(p.run_id, { run_id: p.run_id, season: p.season, gw_from: from, gw_to: to });
          else
            seen.set(p.run_id, {
              ...existing,
              gw_from: Math.min(existing.gw_from, from),
              gw_to: Math.max(existing.gw_to, to),
            });
        }
        const runs =
          playersData.manifest?.runs ??
          [...seen.values()].sort((a, b) => a.run_id.localeCompare(b.run_id));
        const defaultRun = defaultVintageRunId(
          runs,
          nextGw.plans,
          summary.latest_run?.run_id ?? null,
        );
        setState({
          status: "ready",
          summary,
          players: playersData.players,
          teams: teamsData.teams,
          plans: nextGw.plans,
          runs,
          defaultRunId: defaultRun ?? runs[0]?.run_id ?? "",
        });
        setRunId(defaultRun ?? runs[0]?.run_id ?? null);
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

  const view = useMemo(() => {
    if (state.status !== "ready") return null;
    const activeRunId = runId ?? state.defaultRunId;
    const players = state.players.filter((p) => p.run_id === activeRunId);
    const teams = state.teams.filter((t) => t.run_id === activeRunId);
    const run = state.runs.find((r) => r.run_id === activeRunId);
    if (!run || !players.length) return null;

    const gwFrom = run.gw_from;
    const gwTo = run.gw_to;
    const opponentStrength = buildOpponentStrength(teams);
    const opponentIndexOf = (code: number) => opponentStrength.get(code)?.index ?? null;

    const withXp = players
      .map((player) => ({ player, next: gwXp(player, gwFrom), horizon: horizonXpSum(player, gwFrom, gwTo) }))
      .sort((a, b) => (b.next ?? -1) - (a.next ?? -1));

    const topNext = withXp.slice(0, 5);
    const topHorizon = [...withXp].sort((a, b) => (b.horizon ?? -1) - (a.horizon ?? -1)).slice(0, 5);
    const flagged = withXp
      .filter(
        ({ player }) => player.availability_status != null && player.availability_status !== "a",
      )
      .slice(0, 8);

    const teamEase = teams
      .map((team) => {
        const values = team.fixtures
          .map((f) => f.overall_ease_index)
          .filter((v): v is number => v != null);
        return {
          team,
          avgEase: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
        };
      })
      .filter((t): t is { team: TeamRecord; avgEase: number } => t.avgEase != null)
      .sort((a, b) => b.avgEase - a.avgEase);
    const easiest = teamEase.slice(0, 3);
    const hardest = [...teamEase].reverse().slice(0, 3);

    return { run, players, teams, gwFrom, gwTo, opponentIndexOf, topNext, topHorizon, flagged, easiest, hardest };
  }, [state, runId]);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Summary</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!view) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Summary</h1>
        <p className="text-sm text-muted-foreground">
          No recorded forecast runs in this export. Generate a vintage first (see
          dashboard/README.md).
        </p>
      </div>
    );
  }

  const { summary } = state;
  const first = view.players[0];
  const officialPlans = platformPlans(state.plans);
  const customPlans = state.plans.filter((plan) => resolvedPlanKind(plan) === "user_custom");
  const savedCustomId = savedCustomPlanId();
  const customPlan =
    customPlans.find((plan) => plan.optimizer_run_id === savedCustomId) ?? customPlans[0] ?? null;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Summary</h1>
          <p className="text-xs text-muted-foreground">
            {view.run.season} · GW{view.gwFrom}-{view.gwTo} · as of{" "}
            {first?.as_of?.replace("T", " ").slice(0, 16)} UTC · {view.players.length} players ·{" "}
            {view.teams.length} clubs
          </p>
        </div>
        <VintageSelect options={vintageOptions(state.runs, state.plans)} value={runId ?? state.defaultRunId} onChange={setRunId} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Next gameweek">
          {summary.next_gameweek ? (
            <>
              <p className="text-2xl font-semibold">GW{summary.next_gameweek.gw}</p>
              <p className="text-xs text-muted-foreground">
                first kickoff{" "}
                {summary.next_gameweek.first_kickoff?.replace("T", " ").slice(0, 16)} UTC ·{" "}
                {summary.next_gameweek.fixture_count ?? "–"} fixtures
              </p>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Deadlines are not sourced in the export, so none is shown.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">no scheduled fixtures</p>
          )}
        </Card>

        {officialPlans.map((plan) => {
          const week = plan.weeks[0];
          const squadXp = week.players.reduce((a, p) => a + (p.expected_points ?? 0), 0);
          const totalHits = plan.weeks.reduce((a, w) => a + w.hit_points, 0);
          const xi = week.players.filter((p) => p.role === "starting_xi");
          const bench = week.players.filter((p) => p.role !== "starting_xi");
          const captain = xi.find((p) => p.code === week.captain_code);
          const vice = xi.find((p) => p.code === week.vice_captain_code);
          return (
            <Card
              key={plan.optimizer_run_id}
              title={
                resolvedPlanKind(plan) === "platform_default"
                  ? "Platform recommendation — default"
                  : "Platform diagnostic sensitivity"
              }
            >
              <p className="text-sm">
                <span className="text-2xl font-semibold tabular-nums">{fmt(squadXp)}</span>{" "}
                <span className="text-xs text-muted-foreground">GW{week.gw} squad xP</span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                cost {price(week.squad_cost)} · hits -{fmt(totalHits, 0)} · C{" "}
                <span className="font-medium text-foreground">{captain?.web_name ?? "–"}</span> · V{" "}
                <span className="font-medium text-foreground">{vice?.web_name ?? "–"}</span>
              </p>
              <p className="mt-2 text-xs leading-relaxed">
                <span className="text-muted-foreground">XI: </span>
                {xi.map((p) => p.web_name).join(", ")}
              </p>
              <p className="text-xs leading-relaxed">
                <span className="text-muted-foreground">Bench: </span>
                {bench.map((p) => p.web_name).join(", ")}
              </p>
              <p className="mt-1 text-[10px] text-muted-foreground">
                {planDisplayLabel(plan)} · development-only · see the Next GW page
              </p>
            </Card>
          );
        })}
        {customPlan && (
          <Card title="Your custom plan">
            <p className="text-sm">
              <span className="text-2xl font-semibold tabular-nums">
                {fmt(
                  customPlan.weeks[0].players.reduce(
                    (total, player) => total + (player.expected_points ?? 0),
                    0,
                  ),
                )}
              </span>{" "}
              <span className="text-xs text-muted-foreground">
                GW{customPlan.weeks[0].gw} squad xP
              </span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {customPlan.policy.locked_codes.length} locked ·{" "}
              {customPlan.policy.excluded_codes.length} excluded · bench floor{" "}
              {Math.round(customPlan.policy.min_bench_appearance * 100)}%
            </p>
            <p className="mt-2 text-xs">
              This rule-specific scenario stays separate from the platform recommendation.
            </p>
            <a
              className="mt-2 inline-block text-xs font-medium text-primary"
              href={`#plan-builder?run=${encodeURIComponent(customPlan.optimizer_run_id)}`}
            >
              Open your plan in Plan Builder →
            </a>
          </Card>
        )}
        {!officialPlans.length && (
          <Card title="Platform optimizer squads">
            <p className="text-xs text-muted-foreground">
              none in this export — rebuild it with --optimizer-plan inputs
            </p>
          </Card>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title={`Availability watch (reported overlay, GW${view.gwFrom})`}>
          {view.flagged.length ? (
            <ul className="space-y-1.5 text-sm">
              {view.flagged.map(({ player, next }) => (
                <li key={player.code} className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <PlayerPhoto code={player.code} name={player.web_name} />
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{player.web_name}</span>
                      <span className="ml-1 text-xs text-muted-foreground">
                        {player.team_short_name} · {player.position}
                      </span>
                    </span>
                  </span>
                  <span className="flex items-center gap-2 whitespace-nowrap">
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                      {availabilityLabel(player.availability_status)}
                      {player.chance_of_playing != null
                        ? ` ${Math.round(player.chance_of_playing)}%`
                        : ""}
                    </span>
                    <span className="tabular-nums text-xs text-muted-foreground" title="GW xP">
                      {fmt(next)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">no flagged players in this vintage</p>
          )}
          <p className="mt-2 text-[10px] text-muted-foreground">
            Official status/chance fields only — there is no news feed in the read models. An
            overlay never changes the stored distribution.
          </p>
        </Card>

        <Card title={`Players to watch — GW${view.gwFrom} xP`}>
          <ul className="space-y-1.5">
            {view.topNext.map(({ player, next }) => (
              <PlayerLine key={player.code} player={player} value={next} valueLabel={`GW${view.gwFrom} expected points`} />
            ))}
          </ul>
        </Card>

        <Card title={`Players to watch — GW${view.gwFrom}-${view.gwTo} xP`}>
          <ul className="space-y-1.5">
            {view.topHorizon.map(({ player, horizon }) => (
              <PlayerLine key={player.code} player={player} value={horizon} valueLabel={`GW${view.gwFrom}-${view.gwTo} expected points`} />
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Teams to watch — easiest schedules (overall ease, higher = easier)">
          <TeamWatchList teams={view.easiest} opponentIndexOf={view.opponentIndexOf} gwFrom={view.gwFrom} gwTo={view.gwTo} />
        </Card>
        <Card title="Teams to watch — hardest schedules">
          <TeamWatchList teams={view.hardest} opponentIndexOf={view.opponentIndexOf} gwFrom={view.gwFrom} gwTo={view.gwTo} />
        </Card>
      </div>

      <Separator className="my-1" />
      <p className="text-xs text-muted-foreground">
        Headline numbers only — the Fixture matrix and Players pages expose the raw lambdas,
        ease indices, and per-fixture xP behind every figure. Availability is a reported
        overlay valid for the next gameweek, never folded into xP; EV is never compared across
        architectures. Chips colour on opponent strength (green = weak opponent, red = strong).
      </p>
    </div>
  );
}

function TeamWatchList({
  teams,
  opponentIndexOf,
  gwFrom,
  gwTo,
}: {
  teams: { team: TeamRecord; avgEase: number }[];
  opponentIndexOf: (code: number) => number | null;
  gwFrom: number;
  gwTo: number;
}) {
  return (
    <ul className="space-y-3">
      {teams.map(({ team, avgEase }) => {
        const form = team.form?.windows.last_5 ?? null;
        return (
          <li key={team.team_code}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <TeamBadge teamCode={team.team_code} shortName={team.short_name} />
                <span className="font-medium">{team.team_name}</span>
                {team.form && (
                  <Badge variant="outline" className="text-[9px]">
                    form {team.form.season} GW{team.form.as_at_gw}
                  </Badge>
                )}
              </span>
              <span className="tabular-nums text-sm" title="Average overall ease over the horizon">
                {fmt(avgEase)}
              </span>
            </div>
            <p className="mb-1 text-xs tabular-nums text-muted-foreground">
              {form
                ? `W${fmt(form.wins, 0)} D${fmt(form.draws, 0)} L${fmt(form.losses, 0)} · xG ${fmt(
                    form.team_xg_per_match,
                    2,
                  )}/m · xGC ${fmt(form.team_xgc_per_match, 2)}/m`
                : "no form data"}
            </p>
            <FixtureTicker
              fixtures={[...team.fixtures].sort(
                (a, b) => a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""),
              )}
              minGw={gwFrom}
              maxGw={gwTo}
              metricOf={(f) => chipMetric(f, "overall", "opponent", opponentIndexOf(f.opponent_team_code))}
              bucketOf={(f) => chipBucket(f, "overall", "opponent", null, opponentIndexOf(f.opponent_team_code))}
            />
          </li>
        );
      })}
    </ul>
  );
}
