import { useEffect, useState } from "react";
import { Clock3 } from "lucide-react";
import { loadRestSummary, type PlayerRest, type RestSummary } from "@/data/restSummary";
import { matchingRest, type RankedNextPlayer } from "@/lib/summaryRest";
import { PlayerPhoto } from "@/components/Avatars";
import { AvailabilityBadge } from "@/components/AvailabilityBadge";
import { hasCurrentAvailabilityConcern } from "@/lib/availability";

type RestState = { status: "loading" } | { status: "unavailable" } | { status: "ready"; data: RestSummary };
const utcTime = (value: string) => new Date(value).toISOString().slice(0, 16).replace("T", " ");
const matchDate = (value: string) => new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Europe/London" }).format(new Date(value));
const statusLabel = (rest: PlayerRest | null) => rest?.verdict === "midweek_played" ? "Played midweek" : rest?.verdict === "full_rest" ? "No midweek appearance" : "Unknown";

export function SummaryRestTable({ players, gw }: { players: RankedNextPlayer[]; gw: number | null }) {
  const [state, setState] = useState<RestState>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    loadRestSummary().then((data) => { if (!cancelled) setState({ status: "ready", data }); })
      .catch(() => { if (!cancelled) setState({ status: "unavailable" }); });
    return () => { cancelled = true; };
  }, []);
  const report = state.status === "ready" ? state.data : null;

  return <section className="min-w-0 overflow-hidden rounded-xl border bg-card" aria-labelledby="summary-next-players">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
      <div>
        <h2 id="summary-next-players" className="flex items-center gap-2 text-base font-semibold"><Clock3 className="size-4 text-muted-foreground" aria-hidden="true" />Top 15 players{gw === null ? " · next GW" : ` · GW${gw}`}</h2>
        <p className="mt-1 text-xs text-muted-foreground">Ranked by published raw xP for this GW only. Midweek context does not change the ranking or forecast.</p>
      </div>
      <a href="#players" className="text-xs font-medium underline underline-offset-4">View all players</a>
    </div>
    <div className="space-y-1 bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
      {report ? <p>Rest evidence as of <span className="font-medium text-foreground">{utcTime(report.as_of)} UTC</span> · previous {report.window_hours} hours · midweek: Mon–Thu UTC.</p>
        : <p role="status">{state.status === "loading" ? "Loading published rest evidence…" : "Rest evidence unavailable in this published generation. The xP ranking is still usable."}</p>}
      <p>Club participation only; national-team call-ups are not captured. Gaps are kickoff-to-kickoff, not verified recovery or fitness.</p>
    </div>
    {gw === null || players.length === 0 ? <p className="p-4 text-sm text-muted-foreground">
      {gw === null ? "The published next GW is not covered by the selected forecast. Select a current vintage to see this ranking." : "No players with complete published xP for this GW."}
    </p> : <div className="overflow-x-auto" role="region" aria-label="Top 15 players and midweek context" tabIndex={0}>
      <table className="w-full min-w-[900px] text-left text-xs">
        <caption className="sr-only">Top 15 players by raw GW{gw} xP, with separate observed midweek participation and UK calendar-day kickoff gaps.</caption>
        <thead className="bg-muted/40 text-muted-foreground"><tr>
          <th scope="col" className="px-4 py-2.5 font-medium">Player</th>
          <th scope="col" className="px-3 py-2.5 text-right font-medium">xP GW{gw}</th>
          <th scope="col" className="px-3 py-2.5 font-medium">Midweek club football</th>
          <th scope="col" className="px-3 py-2.5 font-medium">Last witnessed match</th>
          <th scope="col" className="px-3 py-2.5 font-medium">Next PL match</th>
          <th scope="col" className="px-4 py-2.5 text-right font-medium">Kickoff gap</th>
        </tr></thead>
        <tbody>{players.map(({ player, xp }, index) => {
          const { rest, reason } = matchingRest(report, player, gw, Date.now());
          const last = rest?.last_appearance;
          const next = rest?.next_fixture;
          const details = [...(rest?.unknown_reasons ?? []), ...(reason ? [reason] : [])];
          return <tr key={player.code} className="border-t align-top hover:bg-muted/20">
            <td className="px-4 py-3"><div className="flex items-center gap-2"><span className="w-4 text-right tabular-nums text-muted-foreground">{index + 1}</span><PlayerPhoto code={player.code} name={player.web_name} /><div><p className="font-medium">{player.web_name}</p><p className="mt-0.5 text-muted-foreground">{player.team_short_name} · {player.position}</p>{hasCurrentAvailabilityConcern(player) && <div className="mt-1"><AvailabilityBadge player={player} /></div>}</div></div></td>
            <td className="px-3 py-3 text-right text-sm font-semibold tabular-nums">{xp.toFixed(1)}</td>
            <td className="max-w-64 px-3 py-3">
              <span className={`inline-flex rounded-md px-2 py-1 font-medium ${rest?.verdict === "midweek_played" ? "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200" : rest?.verdict === "full_rest" ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200" : "bg-muted text-muted-foreground"}`}>{statusLabel(rest)}</span>
              {rest && rest.midweek_appearances > 0 && <p className="mt-1 text-muted-foreground">{rest.midweek_appearances} appearance(s) · {rest.midweek_nominal_minutes == null ? "duration unavailable" : `${rest.midweek_nominal_minutes.toFixed(0)} nominal min`}</p>}
              {rest?.international_window_overlap && <p className="mt-1 text-amber-700 dark:text-amber-300">International window overlaps</p>}
              <details className="mt-1.5 text-muted-foreground"><summary className="cursor-pointer text-[11px] underline-offset-2 hover:underline focus-visible:outline-2">Evidence &amp; limits</summary>
                <div className="mt-1 max-w-60 space-y-1 break-words whitespace-normal text-[11px]">
                  {details.map((text) => <p key={text}>{text}</p>)}
                  {rest?.evidence_versions?.map((source) => <p key={`${source.competition_id}-${source.provider_match_id}-${source.version_id}`}>SDP match {source.provider_match_id} · {source.roster_proven ? "side interpreted" : "side unproven"} · known {source.known_at === null ? "Unavailable" : `${utcTime(source.known_at)} UTC`} · version {source.version_id ?? "Unavailable"}</p>)}
                  {last && <p>Last observed SDP match: {last.provider_match_id}</p>}
                  {last?.observed_team_code != null && last.observed_team_code !== player.team_code && <p>That appearance was for club code {last.observed_team_code}; current forecast club code {player.team_code}. Fixture-time membership is preserved.</p>}
                  <p>Provider nominal period-clock minutes are not FPL minutes. An unknown record never proves rest. This is not an availability recommendation.</p>
                </div>
              </details>
            </td>
            <td className="px-3 py-3">{last ? <><p>{last.opponent_name ?? "Opponent unavailable"} · {matchDate(last.kickoff)}</p><p className="mt-0.5 text-muted-foreground">{last.competition_name}</p><p className="mt-0.5 text-muted-foreground">SDP: {last.nominal_minutes == null ? "Unavailable" : `${last.nominal_minutes.toFixed(0)} nominal min`}{last.fpl_minutes != null && ` · FPL: ${last.fpl_minutes} min`}</p></> : <span className="text-muted-foreground">Unavailable</span>}</td>
            <td className="px-3 py-3">{next?.kickoff ? <><p>{next.opponent_name ?? "Opponent unavailable"} ({next.was_home === true ? "H" : next.was_home === false ? "A" : "?"})</p><p className="mt-0.5 text-muted-foreground">GW{next.gw} · {matchDate(next.kickoff)} UK</p></> : <span className="text-muted-foreground">Unavailable</span>}</td>
            <td className="px-4 py-3 text-right">{rest?.rest_days != null && rest.rest_hours != null ? <span className="inline-block" title={`${rest.rest_hours.toFixed(1)} hours between kickoffs; ${rest.rest_days} calendar days in Europe/London`}><span className="font-medium tabular-nums">{rest.rest_days}d</span><span className="mt-0.5 block text-[10px] text-muted-foreground">UK dates</span></span> : <span className="text-muted-foreground">—</span>}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
  </section>;
}
