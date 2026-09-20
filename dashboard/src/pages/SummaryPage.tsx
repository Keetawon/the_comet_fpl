// Summary landing page: a player-first overview from the same
// read models the exploratory pages use (one SELECTED vintage -- the default architecture
// an optimizer plan references). Sections: gameweek focus, availability,
// availability watch (the reported injury/doubt overlay), top 15 next-GW players with
// separate observed midweek context, and teams to watch (schedule ease with recent form and the next
// fixtures). Every number links back to a page that exposes its primitives; headline EV
// is never compared across architectures.

import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CalendarDays, CircleAlert, Newspaper, Target, UsersRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { FixtureTicker } from "@/components/FixtureTicker";
import { VintageSelect } from "@/components/VintageSelect";
import { SummaryRestTable } from "@/components/SummaryRestTable";
import { NewsFeed } from "@/components/NewsFeed";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadPlayers,
  loadSummary,
} from "@/data/load";
import type {
  DashboardManifest,
  NextGwPlan,
  PlayerRecord,
  SummaryData,
  TeamRecord,
} from "@/data/types";
import { currentAvailability, hasCurrentAvailabilityConcern } from "@/lib/availability";
import { AvailabilityBadge } from "@/components/AvailabilityBadge";
import { summaryNextGw, topNextPlayers } from "@/lib/summaryRest";
import { rawPlayerGameweekXp } from "@/lib/userDraft";
import { chipBucket, chipMetric } from "@/lib/fixtureChips";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import {
  planDisplayLabel,
  platformPlans,
  resolvedPlanKind,
} from "@/lib/nextGw";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";
import { compactInsightScope, publishedInsightProvenance } from "@/lib/insights";
import { isHostedStatic } from "@/lib/pageAccess";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      summary: SummaryData;
      players: PlayerRecord[];
      teams: TeamRecord[];
      plans: NextGwPlan[];
      manifest: DashboardManifest | null;
      runs: { run_id: string; season: string; gw_from: number; gw_to: number }[];
      defaultRunId: string;
    };

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

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
    <section className={`min-w-0 rounded-2xl border bg-card p-4 sm:p-5 ${className ?? ""}`}>
      <h2 className="mb-3 text-base font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
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
          manifest: playersData.manifest ?? teamsData.manifest,
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

    const nextGw = summaryNextGw(state.summary, run);
    const withXp = players
      .map((player) => ({ player, next: nextGw === null ? null : rawPlayerGameweekXp(player, nextGw) }))
      .sort((a, b) => (b.next ?? -Infinity) - (a.next ?? -Infinity) || a.player.code - b.player.code);

    const topNext = topNextPlayers(players, nextGw);
    const flagged = withXp
      .filter(
        ({ player }) => hasCurrentAvailabilityConcern(player),
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

    return { run, players, teams, gwFrom, gwTo, nextGw, opponentIndexOf, topNext, flagged, easiest, hardest };
  }, [state, runId]);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading your gameweek overview…</p>;
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
          The gameweek overview is not available yet. Check back after the next update.
        </p>
      </div>
    );
  }

  const { summary } = state;
  const first = view.players[0];
  const hosted = isHostedStatic();
  const officialPlans = hosted ? [] : platformPlans(state.plans);
  const customPlans = hosted ? [] : state.plans.filter((plan) => resolvedPlanKind(plan) === "user_custom");
  const savedCustomId = hosted ? null : savedCustomPlanId();
  const customPlan =
    customPlans.find((plan) => plan.optimizer_run_id === savedCustomId) ?? customPlans[0] ?? null;
  const visibleTopNext = view.topNext[0];
  const localInsightItems = [
    {
      id: "coverage.visible_scope",
      statement: `${view.players.length} players and ${view.teams.length} clubs are visible for GW${view.gwFrom} through GW${view.gwTo}.`,
    },
    ...(visibleTopNext?.xp == null ? [] : [{
      id: "rank.visible_next_xp",
      statement: `${visibleTopNext.player.web_name} has the highest visible GW${view.nextGw} xP at ${visibleTopNext.xp.toFixed(3)}.`,
    }]),
  ];
  const summaryMatchesVisible = summary.latest_run?.run_id === view.run.run_id;

  return (
    <div className="flex min-w-0 flex-col gap-6 p-4 lg:p-6">
      <header className="overflow-hidden rounded-2xl bg-neutral-950 p-5 text-white sm:p-7">
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-neutral-300">
          <span className="rounded-full bg-white/10 px-3 py-1">THE COMET / MATCHWEEK BRIEFING</span>
          <span>{view.run.season}</span>
        </div>
        <div className="mt-5 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div className="max-w-xl">
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Summary</h1>
            <p className="mt-2 text-base leading-relaxed text-neutral-300">Your gameweek, at a glance. The players, team news and fixtures worth a closer look.</p>
          </div>
          <div className="shrink-0 border-l-2 border-amber-300 pl-4">
            <p className="text-xs font-medium text-neutral-400">Forecast focus</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">{view.nextGw === null ? "Not covered" : `GW${view.nextGw}`}</p>
            <p className="mt-1 text-xs text-neutral-300">{view.players.length} players · {view.teams.length} clubs</p>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/15 pt-4 text-xs text-neutral-300">
          <p className="flex items-center gap-2"><CalendarDays className="size-4" aria-hidden="true" />{view.nextGw !== null && summary.next_gameweek?.first_kickoff
            ? `First kickoff ${summary.next_gameweek.first_kickoff.replace("T", " ").slice(0, 16)} UTC`
            : "Kickoff information unavailable"}</p>
          <p>Forecast as of {first?.as_of?.replace("T", " ").slice(0, 16) ?? "unknown date"} UTC</p>
          {view.nextGw !== null && summary.next_gameweek?.fixture_count != null && <p>{summary.next_gameweek.fixture_count} fixtures</p>}
        </div>
      </header>

      <nav aria-label="Explore this gameweek" className="grid gap-3 sm:grid-cols-3">
        {[
          { href: "#players", title: "Find your next pick", text: "Compare points, price and availability", Icon: UsersRound, tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" },
          { href: "#gw-analysis", title: "Score Prediction", text: "Match outlooks and a ready-to-share briefing", Icon: Target, tone: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" },
          { href: "#news", title: "Read the latest news", text: "Team updates, injuries and manager comments", Icon: Newspaper, tone: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200" },
        ].map(({ href, title, text, Icon, tone }) => <a key={href} href={href} className="group flex min-h-24 items-center gap-3 rounded-2xl border bg-card p-4 transition-colors hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-offset-4">
          <span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${tone}`}><Icon className="size-5" aria-hidden="true" /></span>
          <span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{title}</span><span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{text}</span></span>
          <ArrowUpRight className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" aria-hidden="true" />
        </a>)}
      </nav>

      <div className="grid gap-3">
        <Card title="Availability watch">
          <div className="mb-4 flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-950 dark:bg-amber-950/40 dark:text-amber-100">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <p>Check before picking. Latest FPL reports for up to eight flagged players{view.nextGw === null ? "" : `, ordered by GW${view.nextGw} xP`}. A flag does not change their predicted points.</p>
          </div>
          {view.flagged.length ? (
            <ul className="grid gap-x-6 gap-y-3 text-sm md:grid-cols-2 xl:grid-cols-4">
              {view.flagged.map(({ player, next }) => (
                <li key={player.code} className="space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <PlayerPhoto code={player.code} name={player.web_name} />
                      <span className="min-w-0 truncate">
                        <span className="font-medium">{player.web_name}</span>
                        <span className="ml-1 text-xs text-muted-foreground">
                          {player.team_short_name} · {player.position}
                        </span>
                      </span>
                    </span>
                    <span className="tabular-nums text-xs text-muted-foreground" title="GW xP">
                      {fmt(next)}
                    </span>
                  </div>
                  <AvailabilityBadge player={player} details />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No flagged players in the published current FPL reports.</p>
          )}
          {view.players.some((player) => currentAvailability(player) == null) && (
            <p className="mt-2 text-xs text-muted-foreground">Current availability is unknown for players without a published FPL report; forecast status is retained separately.</p>
          )}
          <a href="#players" className="mt-3 inline-flex min-h-11 items-center text-xs font-medium underline underline-offset-4">Check all players and statuses <ArrowUpRight className="ml-1 size-3.5" aria-hidden="true" /></a>
        </Card>

      </div>

      <SummaryRestTable players={view.topNext} gw={view.nextGw} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="A kinder run of fixtures">
          <p className="mb-4 text-xs text-muted-foreground">Easiest published schedules · GW{view.gwFrom}–{view.gwTo}. Higher ease is better.</p>
          <TeamWatchList teams={view.easiest} opponentIndexOf={view.opponentIndexOf} gwFrom={view.gwFrom} gwTo={view.gwTo} />
        </Card>
        <Card title="A tougher run ahead">
          <p className="mb-4 text-xs text-muted-foreground">Hardest published schedules · GW{view.gwFrom}–{view.gwTo}. Compare the opponents before making a move.</p>
          <TeamWatchList teams={view.hardest} opponentIndexOf={view.opponentIndexOf} gwFrom={view.gwFrom} gwTo={view.gwTo} />
        </Card>
      </div>

      <NewsFeed compact />
      {!hosted && <details className="rounded-2xl border bg-card p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2">Your local plans</summary>
        <p className="my-3 text-xs leading-relaxed text-muted-foreground">Saved planning scenarios, with their own forecast dates. These do not update when news changes.</p>
        <div className="grid gap-3 lg:grid-cols-2">
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
              <p className="mt-1 text-xs text-muted-foreground">Plan as of {plan.as_of ? `${plan.as_of.replace("T", " ").slice(0, 16)} UTC` : "unknown date"}</p>
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
            <p className="mt-1 text-xs text-muted-foreground">Plan as of {customPlan.as_of ? `${customPlan.as_of.replace("T", " ").slice(0, 16)} UTC` : "unknown date"}</p>
            <a
              className="mt-2 inline-block text-xs font-medium text-primary"
              href={`#plan-builder?run=${encodeURIComponent(customPlan.optimizer_run_id)}`}
            >
              Open your plan in Plan Builder →
            </a>
          </Card>
        )}
        {!hosted && !officialPlans.length && (
          <Card title="Platform optimizer squads">
            <p className="text-xs text-muted-foreground">
              No saved platform plan in this update.
            </p>
          </Card>
        )}
        </div>
      </details>}

      <details className="rounded-2xl border bg-card p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2">Data &amp; forecast details</summary>
        <div className="mt-4 space-y-3 text-xs leading-relaxed text-muted-foreground">
          <p>{view.run.season} · GW{view.gwFrom}-{view.gwTo} · forecast as of {first?.as_of?.replace("T", " ").slice(0, 16) ?? "unknown date"} UTC</p>
          <VintageSelect options={vintageOptions(state.runs, state.plans)} value={runId ?? state.defaultRunId} onChange={setRunId} />
          <p className="break-all">Forecast reference: {view.run.run_id}</p>
          <p>xP means expected FPL points, not guaranteed points. Rankings use the selected forecast; the latest FPL availability and observed match information are shown separately.</p>
          <p>Green fixture chips indicate weaker opponents; red indicates stronger opponents. Team form labels identify its season, match count and any provisional results.</p>
          <p>Deadlines are not sourced in this export. The kickoff above is not an FPL deadline.</p>
        </div>
      </details>
      <details className="rounded-2xl border bg-card p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2">More about this overview</summary>
        <div className="mt-4">
      <InsightSummaryPanel
        items={localInsightItems}
        caveats={[
          "xP totals sum already-published values; probabilities are never combined in the browser.",
          "Summary ranks describe one immutable forecast vintage.",
        ]}
        remote={{
          page: "summary",
          provenance: publishedInsightProvenance(state.manifest, {
            ...view.run,
            as_of: view.players[0]?.as_of,
          }),
          scope: compactInsightScope({ gw_from: view.gwFrom, gw_to: view.gwTo }),
          localScopeKey: view.run.run_id,
          unavailableReason: summaryMatchesVisible
            ? undefined
            : "AI explanation is unavailable because the visible vintage differs from summary.json.",
        }}
      />
        </div>
      </details>
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
  if (teams.length === 0) return <p className="text-sm text-muted-foreground">Fixture comparison unavailable for this forecast.</p>;
  return (
    <ul className="space-y-3">
      {teams.map(({ team, avgEase }) => {
        const form = team.form?.windows.last_5 ?? null;
        return (
          <li key={team.team_code}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                <TeamBadge teamCode={team.team_code} shortName={team.short_name} />
                <span className="font-medium">{team.team_name}</span>
                {team.form && (
                  <Badge variant="outline" className="text-[11px]">
                    {team.form.source === "published_team_actuals" ? "Observed" : "Archived"} form {team.form.season} GW{team.form.as_at_gw}
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
              {form?.observations && (
                <> · {form.matches_played} matches
                  {form.observations.provisional_matches > 0 && ` · ${form.observations.provisional_matches} provisional`}
                </>
              )}
            </p>
            <FixtureTicker
              fixtures={[...team.fixtures].sort(
                (a, b) => a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""),
              )}
              minGw={gwFrom}
              maxGw={gwTo}
              metricOf={(f) => chipMetric(f, "overall", "opponent", opponentIndexOf(f.opponent_team_code))}
              bucketOf={(f) => chipBucket(f, "overall", "opponent", opponentIndexOf(f.opponent_team_code))}
            />
          </li>
        );
      })}
    </ul>
  );
}
