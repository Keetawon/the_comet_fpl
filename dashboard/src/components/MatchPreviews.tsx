import { useEffect, useMemo, useState } from "react";
import { TeamBadge } from "@/components/Avatars";
import { Button } from "@/components/ui/button";
import { loadPlayers } from "@/data/load";
import { loadNewsFeed, type PublicNewsFeed } from "@/data/newsFeed";
import { loadRestSummary, type RestSummary } from "@/data/restSummary";
import type { PlayerRecord, TeamRecord } from "@/data/types";
import { buildMatchPreviews, previewNews, previewRest, type MatchPreview } from "@/lib/matchPreview";

type OptionalData<T> = { status: "loading" } | { status: "unavailable" } | { status: "ready"; data: T };
const fieldClass = "min-h-10 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const numeric = (value: number | null | undefined, places = 2) =>
  value != null && Number.isFinite(value) ? value.toFixed(places) : "Unavailable";
const probability = (value: number | null) => value == null ? "Unavailable" : `${(value * 100).toFixed(0)}%`;
const utc = (value: string | null) => value && Number.isFinite(Date.parse(value))
  ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC` : "Unavailable";
const label = (match: MatchPreview) => `${match.home.team.short_name} v ${match.away.team.short_name}`;

function TeamForm({ team, exportCreatedAt }: { team: TeamRecord; exportCreatedAt: string | null }) {
  const form = team.form?.source === "published_team_actuals" && team.form.season === team.season && team.form.windows.last_5.observations
    ? team.form.windows.last_5 : null;
  return <div className="min-w-0 rounded-lg border p-3">
    <h4 className="text-sm font-semibold">{team.team_name}</h4>
    {!form ? <p className="mt-2 text-xs text-muted-foreground">Same-season published form unavailable.</p> : <>
      <p className="mt-1 text-xs font-medium">FPL observed · {team.season} · GW{form.observations!.gw_from}–{form.observations!.gw_to}</p>
      <p className="mt-1 text-xs text-muted-foreground">{numeric(form.matches_played, 0)} fixtures, up to the latest five · {numeric(form.observations?.provisional_matches, 0)} provisional</p>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div><dt className="text-muted-foreground">Goals for / against</dt><dd className="mt-1 font-medium tabular-nums">{numeric(form.goals_for, 0)} / {numeric(form.goals_against, 0)}</dd></div>
        <div><dt className="text-muted-foreground">Wins / draws / losses</dt><dd className="mt-1 font-medium tabular-nums">{numeric(form.wins, 0)} / {numeric(form.draws, 0)} / {numeric(form.losses, 0)}</dd></div>
        <div><dt className="text-muted-foreground">Observed xG / match</dt><dd className="mt-1 font-medium tabular-nums">{numeric(form.team_xg_per_match)}</dd><dd className="mt-1 text-muted-foreground">{numeric(form.observations?.team_xg_matches, 0)} measured fixtures</dd></div>
        <div><dt className="text-muted-foreground">Observed xGC / match</dt><dd className="mt-1 font-medium tabular-nums">{numeric(form.team_xgc_per_match)}</dd><dd className="mt-1 text-muted-foreground">{numeric(form.observations?.team_xgc_matches, 0)} measured fixtures</dd></div>
      </dl>
      <p className="mt-3 text-[11px] text-muted-foreground">Observed form exported {utc(exportCreatedAt)}; separate from the forecast cutoff.</p>
    </>}
  </div>;
}

export interface MatchPreviewsProps {
  teams: TeamRecord[];
  exportCreatedAt: string | null;
}

/** Read-only presentation of published quantities and separately timed current reports. */
export function MatchPreviews({ teams, exportCreatedAt }: MatchPreviewsProps) {
  const [players, setPlayers] = useState<OptionalData<PlayerRecord[]>>({ status: "loading" });
  const [news, setNews] = useState<OptionalData<PublicNewsFeed>>({ status: "loading" });
  const [rest, setRest] = useState<OptionalData<RestSummary>>({ status: "loading" });
  const [gw, setGw] = useState<number | null>(null);
  const [club, setClub] = useState("");
  const [fixture, setFixture] = useState<number | null>(null);
  const [language, setLanguage] = useState<"en" | "th">("en");
  useEffect(() => {
    let active = true;
    loadPlayers().then(data => { if (active) setPlayers({ status: "ready", data: data.players }); })
      .catch(() => { if (active) setPlayers({ status: "unavailable" }); });
    loadNewsFeed().then(data => { if (active) setNews({ status: "ready", data }); })
      .catch(() => { if (active) setNews({ status: "unavailable" }); });
    loadRestSummary().then(data => { if (active) setRest({ status: "ready", data }); })
      .catch(() => { if (active) setRest({ status: "unavailable" }); });
    return () => { active = false; };
  }, []);

  const built = useMemo(() => buildMatchPreviews(teams), [teams]);
  const gameweeks = [...new Set(built.matches.map(match => match.gw))].sort((a, b) => a - b);
  const selectedGw = gw != null && gameweeks.includes(gw) ? gw : gameweeks[0];
  const matches = built.matches.filter(match => match.gw === selectedGw &&
    (!club || match.home.team.team_code === Number(club) || match.away.team.team_code === Number(club)));
  const selected = matches.find(match => match.fixture === fixture) ?? matches[0];
  const clubs = [...new Map(built.matches.flatMap(match => [match.home.team, match.away.team])
    .map(team => [team.team_code, team])).values()].sort((a, b) => a.team_name.localeCompare(b.team_name));
  const playerRows = players.status === "ready" ? players.data : [];
  const newsFeed = news.status === "ready" ? news.data : null;
  const restReport = rest.status === "ready" ? rest.data : null;
  const now = Date.now();
  const newsContext = selected ? previewNews(newsFeed, selected, playerRows, now) : null;
  const restContext = selected ? previewRest(restReport, selected, playerRows, now) : null;
  const vintage = built.matches[0];

  return <section className="min-w-0 space-y-4" aria-label="Match previews">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-2"><h2 className="text-base font-semibold">Match previews</h2><span className="rounded-md bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">Deterministic preview</span></div>
        <p className="mt-1 text-xs text-muted-foreground">Published team forecasts, observed form and current reports in one view.</p>
        {vintage && <p className="mt-1 text-xs text-muted-foreground">Recorded forecast · {vintage.season} · as of {utc(vintage.as_of)}</p>}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">Preview gameweek
          <select className={fieldClass} value={selectedGw ?? ""} disabled={!gameweeks.length} onChange={event => { setGw(Number(event.target.value)); setFixture(null); }}>
            {!gameweeks.length && <option value="">Unavailable</option>}
            {gameweeks.map(value => <option key={value} value={value}>GW{value} · recorded forecast</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">Preview club
          <select className={fieldClass} value={club} onChange={event => { setClub(event.target.value); setFixture(null); }}>
            <option value="">All clubs</option>{clubs.map(team => <option key={team.team_code} value={team.team_code}>{team.team_name}</option>)}
          </select>
        </label>
        <Button variant="outline" className="min-h-10" onClick={() => { setGw(null); setClub(""); setFixture(null); }}>Reset preview</Button>
      </div>
    </div>
    {built.rejected.length > 0 && <details className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground"><summary className="cursor-pointer focus-visible:outline-2">{built.rejected.length} fixture(s) unavailable because their published sides could not be reconciled</summary><ul className="mt-2 space-y-1">{built.rejected.map(row => <li key={`${row.season}-${row.run_id}-${row.fixture}`}>{row.season} · fixture {row.fixture}: {row.reason}</li>)}</ul></details>}
    <p className="text-xs text-muted-foreground">{matches.length} published match{matches.length === 1 ? "" : "es"}{selectedGw != null ? ` in GW${selectedGw}` : ""}. Published expected goals are forecast means, not observed xG or predicted scorelines. Clean-sheet probabilities are shown separately.</p>
    {!matches.length ? <p role="status" className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">No complete published match is available in this scope. Missing evidence remains unavailable.</p> : <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Gameweek match overview">
        {matches.map(match => <button key={match.fixture} type="button" aria-pressed={selected.fixture === match.fixture}
          aria-label={`Preview ${label(match)}, fixture ${match.fixture}`} onClick={() => setFixture(match.fixture)}
          className={`min-w-0 rounded-xl border bg-card p-4 text-left focus-visible:outline-2 focus-visible:outline-offset-2 ${selected.fixture === match.fixture ? "border-primary ring-1 ring-primary" : "hover:bg-muted/30"}`}>
          <span className="block text-[11px] text-muted-foreground">{utc(match.kickoff_time)}</span>
          <span className="mt-3 grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 gap-y-2 text-xs">
            <span /><span className="text-right text-muted-foreground">Exp. goals</span><span className="text-right text-muted-foreground">CS</span>
            {([match.home, match.away] as const).map((side, index) => <span key={side.team.team_code} className="contents">
              <span className="flex min-w-0 items-center gap-2 font-medium"><TeamBadge teamCode={side.team.team_code} shortName={side.team.short_name} /><span className="truncate">{side.team.short_name} <span className="text-muted-foreground">({index === 0 ? "H" : "A"})</span></span></span>
              <span className="text-right font-semibold tabular-nums">{numeric(side.forecast.lambda_for)}</span><span className="text-right tabular-nums">{probability(side.forecast.probability_clean_sheet)}</span>
            </span>)}
          </span>
          <span className="mt-3 block text-[11px] text-muted-foreground">{selected.fixture === match.fixture ? "Viewing details" : "View match details"}</span>
        </button>)}
      </div>
      <section className="min-w-0 rounded-xl border bg-card p-4 sm:p-5" aria-label="Selected match details">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div><h3 className="text-base font-semibold">{selected.home.team.team_name} v {selected.away.team.team_name}</h3><p className="mt-1 text-xs text-muted-foreground">GW{selected.gw} · fixture {selected.fixture} · {utc(selected.kickoff_time)}</p></div>
          <span className="rounded-md bg-muted px-2 py-1 text-[11px] text-muted-foreground">Recorded forecast</span>
        </div>
        {(selected.home.forecast.stage_a_league_average_team || selected.away.forecast.stage_a_league_average_team) && <p className="mt-3 text-xs text-muted-foreground">Published league-average fallback: {[selected.home, selected.away].filter(side => side.forecast.stage_a_league_average_team).map(side => side.team.team_name).join(", ")}.</p>}
        <h4 className="mt-5 text-sm font-semibold">Recent form · FPL observed</h4>
        <p className="mt-1 text-xs text-muted-foreground">Same-season ended matches only. A short season stays short; provisional results may change.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2"><TeamForm team={selected.home.team} exportCreatedAt={exportCreatedAt} /><TeamForm team={selected.away.team} exportCreatedAt={exportCreatedAt} /></div>
        <div className="mt-5 border-t pt-4">
          <h4 className="text-sm font-semibold">Current reported context</h4>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">These reports may postdate the recorded forecast. News and observed workload do not change its expected goals, clean-sheet probabilities or player xP. Absence of a report does not establish fitness or availability.</p>
          {players.status === "unavailable" && <p className="mt-2 text-xs text-muted-foreground">Published player identities unavailable; player-linked context cannot be verified.</p>}
          <div className="mt-4 grid min-w-0 gap-5 lg:grid-cols-2">
            <section className="min-w-0" aria-label="Match club news">
              <div className="flex flex-wrap items-center justify-between gap-2"><h5 className="text-sm font-semibold">Reported club news</h5><div className="flex gap-1" role="group" aria-label="News language">{(["en", "th"] as const).map(value => <Button key={value} variant={language === value ? "secondary" : "ghost"} size="sm" aria-pressed={language === value} onClick={() => setLanguage(value)}>{value === "en" ? "English" : "ไทย"}</Button>)}</div></div>
              {newsFeed && <p className="mt-1 text-[11px] text-muted-foreground">Feed published {utc(newsFeed.generated_at)}</p>}
              {newsFeed?.demo && <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300">DEMO: synthetic news examples, not current reports.</p>}
              {news.status === "loading" ? <p className="mt-3 text-xs text-muted-foreground">Loading published news…</p> : news.status === "unavailable" ? <p className="mt-3 text-xs text-muted-foreground">News unavailable in this published generation.</p> : newsContext?.reason ? <p className="mt-3 text-xs text-muted-foreground">{newsContext.reason}</p> : !newsContext?.stories.length ? <p className="mt-3 text-xs text-muted-foreground">No eligible linked reports for these clubs. General news is available on the News page.</p> : <div className="mt-3 space-y-3">{newsContext.stories.slice(0, 4).map(story => {
                const translated = language === "th" && story.title.th != null && story.summary.th != null;
                return <article key={story.id} className="min-w-0 rounded-lg border p-3">
                  <p className="text-[11px] text-muted-foreground">{story.source_name} · {story.team_name} · {story.rendering === "ai_summary" ? "Published AI summary" : "Source text"}</p>
                  <h6 className="mt-1 break-words text-sm font-medium" lang={translated ? "th" : "en"}>{translated ? story.title.th : story.title.en}</h6>
                  {language === "th" && !translated && <p className="mt-1 text-[11px] text-muted-foreground">Thai translation pending · showing English</p>}
                  <p className="mt-2 whitespace-pre-line break-words text-xs leading-relaxed" lang={translated ? "th" : "en"}>{translated ? story.summary.th : story.summary.en}</p>
                  <p className="mt-2 text-[11px] text-muted-foreground">Source published {utc(story.published_at)} · known {utc(story.known_at)}</p>
                  <div className="mt-2 flex flex-wrap gap-4 text-xs"><a href={story.source_url} target="_blank" rel="noopener noreferrer" className="py-1 underline underline-offset-4">Original source</a><a href={`#news?story=${encodeURIComponent(story.id)}&lang=${language}`} className="py-1 underline underline-offset-4">Open story</a></div>
                </article>;
              })}</div>}
              {!!newsContext?.rejected.length && <details className="mt-3 rounded-lg border border-dashed p-3 text-xs text-muted-foreground"><summary className="cursor-pointer focus-visible:outline-2">{newsContext.rejected.length} linked report(s) excluded because their evidence could not be matched</summary><ul className="mt-2 space-y-2">{newsContext.rejected.map(row => <li key={row.id}><p>{row.reason}</p><p className="mt-1 break-all text-[11px]">Story {row.id}</p></li>)}</ul></details>}
              <p className="mt-3 text-[11px] text-muted-foreground">Up to four latest eligible club reports. Selected sources only; no inference about this match or its starting XI.</p>
              <a href={`#news?lang=${language}`} className="mt-2 inline-block py-1 text-xs underline underline-offset-4">View all news and source coverage</a>
            </section>
            <section className="min-w-0" aria-label="Match observed workload">
              <h5 className="text-sm font-semibold">Witnessed club workload</h5>
              {restReport && <p className="mt-2 text-[11px] text-muted-foreground">Rest evidence as of {utc(restReport.as_of)} · previous {restReport.window_hours} hours · midweek: Mon–Thu UTC</p>}
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Kickoff gaps are not verified recovery or fitness. Nominal period-clock minutes are not FPL minutes or physical-load measurements. National-team appearances are not captured.</p>
              {rest.status === "loading" || players.status === "loading" ? <p className="mt-3 text-xs text-muted-foreground">Loading published workload evidence…</p> : rest.status === "unavailable" ? <p className="mt-3 text-xs text-muted-foreground">Rest evidence unavailable in this published generation.</p> : restContext?.reason ? <p className="mt-3 text-xs text-muted-foreground">{restContext.reason}</p> : null}
              {restContext && players.status === "ready" && <>
                <p className="mt-3 text-xs text-muted-foreground">{restContext.matched_count} of {restContext.total_players} published players have a record matched to this exact fixture. A matched record may still report unknown coverage.</p>
                <details className="mt-3 rounded-lg border p-3"><summary className="cursor-pointer text-xs font-medium focus-visible:outline-2">Player evidence and gaps ({restContext.total_players})</summary><div className="mt-3 divide-y">{restContext.rows.map(row => <div key={row.player.code} className="py-3 first:pt-0">
                  <p className="text-xs font-medium">{row.player.web_name} · {row.player.team_short_name}</p>
                  <p className="mt-1 text-xs">{row.rest?.verdict === "midweek_played" ? "Played midweek" : row.rest?.verdict === "full_rest" ? "No witnessed midweek appearance" : "Unknown"}{row.rest && row.rest.midweek_appearances > 0 && ` · ${row.rest.midweek_appearances} appearances · ${numeric(row.rest.midweek_nominal_minutes, 0)} nominal min`}</p>
                  {row.rest?.last_appearance && <p className="mt-1 text-[11px] text-muted-foreground">Last witnessed: {row.rest.last_appearance.competition_name} · {row.rest.last_appearance.opponent_name ?? "opponent unavailable"} · {utc(row.rest.last_appearance.kickoff)} · {numeric(row.rest.last_appearance.nominal_minutes, 0)} nominal min{row.rest.last_appearance.fpl_minutes != null && ` · ${row.rest.last_appearance.fpl_minutes} FPL min`}{row.rest.last_appearance.observed_team_code != null && row.rest.last_appearance.observed_team_code !== row.player.team_code && ` · observed club code ${row.rest.last_appearance.observed_team_code}`}</p>}
                  {row.rest && <p className="mt-1 text-[11px] text-muted-foreground">Kickoff gap: {numeric(row.rest.rest_hours, 1)} hours · {numeric(row.rest.rest_days, 0)} UK calendar days</p>}
                  {row.rest?.international_window_overlap && <p className="mt-1 text-[11px] text-muted-foreground">International window overlaps.</p>}
                  {[...(row.rest?.unknown_reasons ?? []), ...(row.reason ? [row.reason] : [])].map(reason => <p key={reason} className="mt-1 break-words text-[11px] text-muted-foreground">{reason}</p>)}
                </div>)}</div></details>
              </>}
            </section>
          </div>
        </div>
      </section>
    </>}
  </section>;
}
