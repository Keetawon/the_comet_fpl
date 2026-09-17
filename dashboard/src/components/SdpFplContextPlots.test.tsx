import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SdpMatch } from "@/data/sdpStats";
import { fplSupplement, sdpMatch, shooting, xg } from "@/test/sdpFixture";
import type { SdpEntity, SdpFilters } from "@/lib/sdpStats";
import { SdpFplContextPlots } from "./SdpFplContextPlots";

function receipt(open: number, set: number, own: number, unknown: number): NonNullable<SdpMatch["goal_patterns"]> {
  return { open_play_goals: open, set_piece_goals: unknown ? null : set, confirmed_set_piece_goals: set,
    own_goals_received: own, unclassified_goals: unknown, total_goals: open + set + own + unknown,
    source_version: "synthetic-v1", raw_payload_sha256: "a".repeat(64), source_known_at: "2026-09-07T08:00:00Z",
    audited_at: "2026-09-14T03:00:00Z", evidence_urls: [], method: "audited_goal_accounting_v1" };
}

function inputs() {
  const rows = [
    sdpMatch({ sdp: { shots: 4, shots_on_target: 2, expected_goals: 1, shots_allowed: 6, shots_on_target_allowed: 3, expected_goals_allowed: .6 }, fpl: { goals_scored: 1, goals_conceded: 0 }, goal_patterns: receipt(1, 0, 0, 0) }),
    sdpMatch({ fixture: 2, gw: 2, sdp: { shots: 16, shots_on_target: 8, expected_goals: 1, shots_allowed: 4, shots_on_target_allowed: 1, expected_goals_allowed: .4 }, fpl: { goals_scored: 3, goals_conceded: 2 }, goal_patterns: receipt(0, 1, 1, 1) }),
  ];
  const teams: SdpEntity[] = [{ id: "team:3", name: "Arsenal", clubs: "ARS", position: "", code: null, teamCode: 3, rows }];
  const metrics = [shooting, xg,
    ...["shots_on_target", "shots_inside_box", "shots_allowed", "shots_on_target_allowed", "expected_goals_allowed", "saves"].map(key => ({ ...shooting, key, label: key })),
    ...["goals_scored", "goals_conceded"].map(key => ({ ...shooting, key, label: key, source: "fpl" as const })),
  ];
  const filters: SdpFilters = { season: "2026-27", from: 1, to: 2, recent: "all", team: "all", search: "", venue: "all", position: "all", minMinutes: 0 };
  return { teams, league: teams, teamMatches: rows, metrics, filters, asOf: "2026-09-14T03:00:00Z", selectedId: "team:3", onSelectTeam: vi.fn() };
}

describe("four observed team context plots", () => {
  it("switches axes independently with matched shot shares and exact opponent box-shot counts", async () => {
    const user = userEvent.setup(); const props = inputs();
    props.teams[0].rows[1].sdp.shots_on_target = 2;
    props.teams[0].rows.forEach((row, i) => { row.sdp.shots_inside_box = 2 + i * 4; });
    const other = props.teamMatches.map((row, i) => ({ ...row, team_code: row.opponent_team_code,
      opponent_team_code: row.team_code, was_home: !row.was_home, sdp: { shots_inside_box: 1 + i * 2 } }));
    // Opponents remain outside the visible home-only population; prior-season IDs cannot collide.
    props.teamMatches = [...props.teamMatches, ...other, { ...other[0], season: "2025-26", sdp: { shots_inside_box: 99 } }];
    const before = JSON.stringify(props);
    render(<SdpFplContextPlots {...props} filters={{ ...props.filters, venue: "home" }} />);
    const attack = screen.getByRole("article", { name: "Attack plot panel" });
    const defence = screen.getByRole("article", { name: "Defence plot panel" });
    const a = () => within(attack).getByTestId("analytics-point");
    const d = () => within(defence).getByTestId("analytics-point");
    expect(a()).toHaveAccessibleName(/SOT \/ all shots \(%\): 20%;/); // 4/20, not mean(2/4, 2/16).
    await user.selectOptions(screen.getByRole("combobox", { name: "Attack X-axis" }), "volume");
    expect(a()).toHaveAccessibleName(/SOT \/match: 2;.*xG \/match: 1/);
    expect(d()).toHaveAccessibleName(/SOT conceded \/ all shots conceded \(%\): 40%;/);
    await user.selectOptions(screen.getByRole("combobox", { name: "Attack X-axis" }), "box");
    expect(a()).toHaveAccessibleName(/Shots inside box \/match: 4;.*xG \/match: 1/);
    await user.selectOptions(screen.getByRole("combobox", { name: "Defence X-axis" }), "box");
    expect(d()).toHaveAccessibleName(/Shots inside box conceded \/match: 2;.*xGA \/match: 0.5/);
    await user.selectOptions(screen.getByRole("combobox", { name: "Defence X-axis" }), "volume");
    expect(d()).toHaveAccessibleName(/SOT conceded \/match: 2;.*xGA \/match: 0.5/);
    await user.selectOptions(screen.getByRole("combobox", { name: "Attack X-axis" }), "share");
    expect(a()).toHaveAccessibleName(/SOT \/ all shots \(%\): 20%;/);
    expect(JSON.stringify(props)).toBe(before);
  });

  it.each(["missing", "duplicate", "wrong-team", "wrong-venue", "wrong-gw", "wrong-kickoff", "wrong-provider", "missing-stat"])(
    "keeps conceded box shots unavailable on %s reciprocal evidence", (fault) => {
      const props = inputs();
      const other = props.teamMatches.map(row => ({ ...row, team_code: row.opponent_team_code,
        opponent_team_code: row.team_code, was_home: !row.was_home, sdp: { shots_inside_box: 3 as number | null } }));
      if (fault === "missing") other.pop();
      if (fault === "duplicate") other.push({ ...other[0] });
      if (fault === "wrong-team") other[0].opponent_team_code = 999;
      if (fault === "wrong-venue") other[0].was_home = !other[0].was_home;
      if (fault === "wrong-gw") other[0].gw = 99;
      if (fault === "wrong-kickoff") other[0].kickoff_time = "2026-08-23T14:00:00Z";
      if (fault === "wrong-provider") other[0].provider_match_id = 999;
      if (fault === "missing-stat") other[0].sdp.shots_inside_box = null;
      render(<SdpFplContextPlots {...props} teamMatches={[...props.teamMatches, ...other]} />);
      fireEvent.change(screen.getByRole("combobox", { name: "Defence X-axis" }), { target: { value: "box" } });
      const defence = screen.getByRole("article", { name: "Defence plot panel" });
      expect(within(defence).queryByTestId("analytics-point")).not.toBeInTheDocument();
      expect(within(defence).getByRole("status")).toHaveTextContent("Missing observations remain unavailable");
      expect(within(screen.getByRole("article", { name: "Attack plot panel" })).getByTestId("analytics-point")).toBeInTheDocument();
    });

  it("keeps zero-denominator percentages unavailable while allowing observed zero volumes", () => {
    const props = inputs();
    props.teams[0].rows.forEach(row => { row.sdp.shots = 0; row.sdp.shots_on_target = 0; });
    render(<SdpFplContextPlots {...props} />);
    const attack = screen.getByRole("article", { name: "Attack plot panel" });
    expect(within(attack).queryByTestId("analytics-point")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Attack X-axis" }), { target: { value: "volume" } });
    expect(within(attack).getByTestId("analytics-point")).toHaveAccessibleName(/SOT \/match: 0;/);
  });

  it("uses consistent matched observations and source-labelled details across four panels", () => {
    const props = inputs(); const before = JSON.stringify(props);
    render(<SdpFplContextPlots {...props} />);
    const attack = screen.getByRole("article", { name: "Attack plot panel" });
    const defence = screen.getByRole("article", { name: "Defence plot panel" });
    const finishing = screen.getByRole("article", { name: "Goals vs xG plot panel" });
    const patterns = screen.getByRole("article", { name: "Goal patterns plot panel" });
    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(attack).toHaveClass("sdp-attack-plot"); expect(defence).toHaveClass("sdp-defence-plot");
    expect(finishing).toHaveClass("sdp-finishing-plot"); expect(patterns).toHaveClass("sdp-pattern-plot");
    const a = within(attack).getByTestId("analytics-point"), d = within(defence).getByTestId("analytics-point");
    expect(a).toHaveAccessibleName(/SDP SOT \/ all shots \(%\): 50%; SDP \/ marked FPL xG \/match: 1/);
    expect(d).toHaveAccessibleName(/SDP SOT conceded \/ all shots conceded \(%\): 40%; SDP \/ marked FPL xGA \/match: 0.5/);
    expect(a).toHaveAttribute("r", "5"); expect(d).toHaveAttribute("r", "5");
    fireEvent.focus(a);
    const tooltip = within(attack).getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Goals /match · FPL2");
    expect(tooltip).toHaveTextContent("SOT / all shots · SDP50%");
    expect(tooltip).toHaveTextContent("Shots /match · SDP10");
    expect(tooltip).toHaveTextContent("SOT /match · SDP5");
    expect(tooltip).toHaveTextContent("xG /shot · SDP / marked FPL0.1");
    fireEvent.blur(a); fireEvent.focus(d);
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("Team clean sheets / matches · FPL1/2");
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("Saves /match · SDP—");
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("SOT conceded / all shots conceded · SDP40%");
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("Shots conceded /match · SDP5");
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("SOT conceded /match · SDP2");
    const f = within(finishing).getByTestId("analytics-point");
    expect(f).toHaveAccessibleName(/SDP \/ marked FPL xG \/match: 1; FPL Goals \/match: 2/);
    expect(f).toHaveAccessibleName(/xG total · SDP \/ marked FPL: 2; Goals total · FPL: 4; Goals minus xG · observed total: 2/);
    expect(finishing).toHaveTextContent("does not predict future finishing");
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/2 matched observations; Open play: 1; Set piece \(confirmed\): 1; Opponent own goal: 1; Unclassified: 1; Total goals: 4/);
    expect([...patterns.querySelectorAll("[data-pattern]")].map(segment => segment.getAttribute("data-count"))).toEqual(["1", "1", "1", "1"]);
    expect(JSON.stringify(props)).toBe(before);
  });

  it("links selection with click and keyboard without changing point values or radii", () => {
    const props = inputs(); const { rerender } = render(<SdpFplContextPlots {...props} selectedId={null} />);
    const points = screen.getAllByTestId("analytics-point");
    const coordinates = points.map(p => [p.getAttribute("cx"), p.getAttribute("cy"), p.getAttribute("r")]);
    fireEvent.click(points[0]); expect(props.onSelectTeam).toHaveBeenLastCalledWith("team:3");
    fireEvent.keyDown(points[1], { key: "Enter" }); expect(props.onSelectTeam).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(points[1], { key: " " }); expect(props.onSelectTeam).toHaveBeenCalledTimes(3);
    const patterns = screen.getByRole("article", { name: "Goal patterns plot panel" });
    fireEvent.click(within(patterns).getByRole("button", { name: /^Arsenal;/ })); expect(props.onSelectTeam).toHaveBeenCalledTimes(4);
    rerender(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByTestId("analytics-point").every(p => p.getAttribute("aria-pressed") === "true")).toBe(true);
    expect(screen.getAllByTestId("analytics-point").map(p => [p.getAttribute("cx"), p.getAttribute("cy"), p.getAttribute("r")])).toEqual(coordinates);
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("excludes incomplete pairs separately, preserves zero observations and labels FPL supplements", () => {
    const props = inputs();
    props.teams[0].rows.forEach(row => {
      row.sdp.expected_goals = null; row.display_supplements = { expected_goals: fplSupplement(row, 2) };
      row.sdp.shots_on_target = 0; row.sdp.shots_on_target_allowed = null;
    });
    const corrected = props.teams[0].rows[1];
    corrected.sdp.shots_on_target = null;
    corrected.display_corrections = { shots_on_target: {
      correction_id: "synthetic-sot-zero", value: 0, evidence_class: "owner_confirmed_display_correction",
      owner_confirmation_recorded_at: props.asOf, source_known_at: corrected.known_at,
      provider_match_id: 2, provider_field: "ontargetScoringAtt", provider_field_state: "omitted",
      raw_payload_sha256: "a".repeat(64), corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero",
      relation: "direct", subject_team_code: 3,
    } };
    const original = JSON.stringify(props);
    render(<SdpFplContextPlots {...props} />);
    const a = within(screen.getByRole("article", { name: "Attack plot panel" })).getByTestId("analytics-point");
    expect(a).toHaveAccessibleName(/SOT \/ all shots \(%\): 0% ‡; SDP \/ marked FPL xG \/match: 2 \[FPL\]/);
    expect(within(screen.getByRole("article", { name: "Goals vs xG plot panel" })).getByTestId("analytics-point")).toHaveAccessibleName(/SDP \/ marked FPL xG \/match: 2 \[FPL\]; FPL Goals \/match: 2/);
    const defence = screen.getByRole("article", { name: "Defence plot panel" });
    expect(within(defence).queryByTestId("analytics-point")).not.toBeInTheDocument();
    expect(within(defence).getByRole("status")).toHaveTextContent("Missing observations remain unavailable");
    expect(JSON.stringify(props)).toBe(original);
  });

  it("keeps the complete-pair league benchmark cohort when visible clubs are filtered out", () => {
    const props = inputs(); const { rerender } = render(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByText(/League median: 1 eligible clubs/, { selector: "p" })).toHaveLength(3);
    rerender(<SdpFplContextPlots {...props} teams={[]} />);
    expect(screen.getAllByText(/0\/0 visible clubs.*League median: 1 eligible clubs/, { selector: "p" })).toHaveLength(3);
    expect(screen.queryByTestId("analytics-point")).not.toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Goal patterns plot panel" })).queryByRole("button", { name: /matched observations/ })).not.toBeInTheDocument();
    rerender(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(3);
  });

  it("keeps explicit zero goals but does not combine disjoint xG/goals coverage or missing receipts", () => {
    const props = inputs();
    props.teams[0].rows.forEach(row => {
      row.sdp.expected_goals = 0; row.fpl!.goals_scored = 0;
      row.goal_patterns = receipt(0, 0, 0, 0);
    });
    const { rerender } = render(<SdpFplContextPlots {...props} />);
    const finishing = screen.getByRole("article", { name: "Goals vs xG plot panel" });
    const patterns = screen.getByRole("article", { name: "Goal patterns plot panel" });
    expect(within(finishing).getByTestId("analytics-point")).toHaveAccessibleName(/xG \/match: 0; FPL Goals \/match: 0/);
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/Open play: 0; Set piece \(confirmed\): 0; Opponent own goal: 0; Unclassified: 0; Total goals: 0/);
    expect([...patterns.querySelectorAll<HTMLElement>("[data-pattern]")].every(segment => segment.style.width === "0%")).toBe(true);
    props.teams[0].rows[0].sdp.expected_goals = null;
    props.teams[0].rows[1].fpl!.goals_scored = null;
    delete props.teams[0].rows[1].goal_patterns;
    props.teams[0].rows[1].sdp.open_play_goals = 3;
    props.teams[0].rows[1].sdp.set_piece_goals = 2;
    rerender(<SdpFplContextPlots {...props} />);
    expect(within(finishing).queryByTestId("analytics-point")).not.toBeInTheDocument();
    expect(within(finishing).getByRole("status")).toHaveTextContent("Missing observations remain unavailable");
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/Unavailable goal total; 1\/2 match receipts/);
    expect(patterns.querySelector("[data-pattern]")).toBeNull();
  });

  it("uses the same selected match scope for all four charts without changing the inputs", () => {
    const props = inputs();
    const teams = props.teams.map(team => ({ ...team, rows: team.rows.slice(0, 1) }));
    const before = JSON.stringify(props);
    render(<SdpFplContextPlots {...props} teams={teams} filters={{ ...props.filters, to: 1, venue: "home" }} />);
    expect(screen.getAllByTestId("analytics-point").every(point => point.getAttribute("aria-label")?.includes("1 matched observations"))).toBe(true);
    expect(within(screen.getByRole("article", { name: "Goals vs xG plot panel" })).getByTestId("analytics-point")).toHaveAccessibleName(/xG \/match: 1; FPL Goals \/match: 1/);
    expect(within(screen.getByRole("article", { name: "Goal patterns plot panel" })).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/1 matched observations; Open play: 1; Set piece \(confirmed\): 0; Opponent own goal: 0; Unclassified: 0; Total goals: 1/);
    expect(JSON.stringify(props)).toBe(before);
  });

  it("retains known goals when one match lacks a breakdown and updates when a receipt arrives", () => {
    const props = inputs(); const row = props.teams[0].rows[1];
    row.goal_patterns = null; row.sdp.open_play_goals = 1;
    const before = JSON.stringify(props);
    const { rerender } = render(<SdpFplContextPlots {...props} />);
    const patterns = screen.getByRole("article", { name: "Goal patterns plot panel" });
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/Open play: 2; Set piece \(confirmed\): 0; Opponent own goal: 0; Unclassified: 2; Total goals: 4; Goal-origin breakdown unavailable for 1\/2 matches/);
    expect(within(patterns).getByText("Origin breakdown missing: 1/2 matches")).toBeInTheDocument();
    expect(patterns.querySelector('[data-pattern="unclassified_goals"]')).toHaveAttribute("data-count", "2");
    expect(JSON.stringify(props)).toBe(before);
    row.goal_patterns = receipt(1, 1, 1, 0);
    rerender(<SdpFplContextPlots {...props} />);
    expect(within(patterns).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/Open play: 2; Set piece \(confirmed\): 1; Opponent own goal: 1; Unclassified: 0; Total goals: 4/);
    expect(within(patterns).queryByText(/Origin breakdown missing:/)).not.toBeInTheDocument();
  });

  it("sorts observed totals descending, keeps zero before missing and breaks ties consistently", () => {
    const props = inputs();
    const teams = [
      { name: "Missing", goals: null }, { name: "Zero", goals: 0 },
      { name: "Zulu", goals: 4 }, { name: "Most", goals: 12 }, { name: "Alpha", goals: 4 },
    ].map(({ name, goals }, i) => ({ ...props.teams[0], id: `team:${i}`, name,
      rows: [sdpMatch({ goal_patterns: goals === null ? null : receipt(goals, 0, 0, 0) })],
    }));
    const before = JSON.stringify(teams);
    const { rerender } = render(<SdpFplContextPlots {...props} teams={teams} />);
    const order = () => within(screen.getByRole("group", { name: /Observed goal-pattern totals/ }))
      .getAllByRole("button").map(row => row.getAttribute("aria-label")!.split(";")[0]);
    expect(order()).toEqual(["Most", "Alpha", "Zulu", "Zero", "Missing"]);
    rerender(<SdpFplContextPlots {...props} teams={[...teams].reverse()} />);
    expect(order()).toEqual(["Most", "Alpha", "Zulu", "Zero", "Missing"]);
    expect(JSON.stringify(teams)).toBe(before);
  });

  it("expands the same chart, preserves selection and scope, and returns with Escape", async () => {
    const user = userEvent.setup();
    const props = inputs();
    const { rerender } = render(<SdpFplContextPlots {...props} />);
    const rows = screen.getByRole("group", { name: /Observed goal-pattern totals/ });
    const before = rows.innerHTML;
    expect(rows).toHaveClass("max-h-80");
    await user.click(screen.getByRole("button", { name: "Enter Goal patterns chart fullscreen" }));
    const dialog = screen.getByRole("dialog", { name: "Goal patterns chart fullscreen" });
    expect(within(dialog).getByRole("group", { name: /Observed goal-pattern totals/ })).toBe(rows);
    expect(rows).not.toHaveClass("max-h-80");
    expect(rows.innerHTML).toBe(before);
    await user.click(within(dialog).getByRole("button", { name: /^Arsenal;/ }));
    expect(props.onSelectTeam).toHaveBeenLastCalledWith("team:3");
    expect(within(dialog).getByRole("button", { name: /^Arsenal;/ })).toHaveAttribute("aria-pressed", "true");
    const teams = props.teams.map(team => ({ ...team, rows: team.rows.slice(0, 1) }));
    rerender(<SdpFplContextPlots {...props} teams={teams} filters={{ ...props.filters, to: 1 }} />);
    expect(within(dialog).getByRole("button", { name: /^Arsenal;/ })).toHaveAccessibleName(/1 matched observations.*Total goals: 1.*GW1–1/);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(rows).toHaveClass("max-h-80");
    expect(screen.getByRole("button", { name: "Enter Goal patterns chart fullscreen" })).toHaveFocus();
  });
});
