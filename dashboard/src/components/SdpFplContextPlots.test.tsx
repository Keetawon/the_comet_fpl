import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { fplSupplement, sdpMatch, shooting, xg } from "@/test/sdpFixture";
import type { SdpEntity, SdpFilters } from "@/lib/sdpStats";
import { SdpFplContextPlots } from "./SdpFplContextPlots";

function inputs() {
  const rows = [
    sdpMatch({ sdp: { shots: 4, shots_on_target: 2, expected_goals: 1, shots_allowed: 6, shots_on_target_allowed: 3, expected_goals_allowed: .6 }, fpl: { goals_scored: 1, goals_conceded: 0 } }),
    sdpMatch({ fixture: 2, gw: 2, sdp: { shots: 16, shots_on_target: 8, expected_goals: 1, shots_allowed: 4, shots_on_target_allowed: 1, expected_goals_allowed: .4 }, fpl: { goals_scored: 3, goals_conceded: 2 } }),
  ];
  const teams: SdpEntity[] = [{ id: "team:3", name: "Arsenal", clubs: "ARS", position: "", code: null, teamCode: 3, rows }];
  const metrics = [shooting, xg,
    ...["shots_on_target", "shots_allowed", "shots_on_target_allowed", "expected_goals_allowed", "saves"].map(key => ({ ...shooting, key, label: key })),
    ...["goals_scored", "goals_conceded"].map(key => ({ ...shooting, key, label: key, source: "fpl" as const })),
  ];
  const filters: SdpFilters = { season: "2026-27", from: 1, to: 2, recent: "all", team: "all", search: "", venue: "all", position: "all", minMinutes: 0 };
  return { teams, league: teams, metrics, filters, asOf: "2026-09-14T03:00:00Z", selectedId: "team:3", onSelectTeam: vi.fn() };
}

describe("observed attack and defence context plots", () => {
  it("uses matched per-match averages, source-labelled details and two distinct themes", () => {
    const props = inputs(); const before = JSON.stringify(props);
    render(<SdpFplContextPlots {...props} />);
    const attack = screen.getByRole("article", { name: "Attack plot panel" });
    const defence = screen.getByRole("article", { name: "Defence plot panel" });
    expect(attack).toHaveClass("sdp-attack-plot"); expect(defence).toHaveClass("sdp-defence-plot");
    const a = within(attack).getByTestId("analytics-point"), d = within(defence).getByTestId("analytics-point");
    expect(a).toHaveAccessibleName(/SDP SOT \/match: 5; SDP \/ marked FPL xG \/match: 1/);
    expect(d).toHaveAccessibleName(/SDP SOT conceded \/match: 2; SDP \/ marked FPL xGA \/match: 0.5/);
    expect(a).toHaveAttribute("r", "5"); expect(d).toHaveAttribute("r", "5");
    fireEvent.focus(a);
    const tooltip = within(attack).getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Goals /match · FPL2");
    expect(tooltip).toHaveTextContent("SOT / all shots · SDP50%");
    expect(tooltip).toHaveTextContent("xG /shot · SDP / marked FPL0.1");
    fireEvent.blur(a); fireEvent.focus(d);
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("Team clean sheets / matches · FPL1/2");
    expect(within(defence).getByRole("tooltip")).toHaveTextContent("Saves /match · SDP—");
    expect(JSON.stringify(props)).toBe(before);
  });

  it("links selection with click and keyboard without changing point values or radii", () => {
    const props = inputs(); const { rerender } = render(<SdpFplContextPlots {...props} selectedId={null} />);
    const points = screen.getAllByTestId("analytics-point");
    const coordinates = points.map(p => [p.getAttribute("cx"), p.getAttribute("cy"), p.getAttribute("r")]);
    fireEvent.click(points[0]); expect(props.onSelectTeam).toHaveBeenLastCalledWith("team:3");
    fireEvent.keyDown(points[1], { key: "Enter" }); expect(props.onSelectTeam).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(points[1], { key: " " }); expect(props.onSelectTeam).toHaveBeenCalledTimes(3);
    rerender(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByTestId("analytics-point").every(p => p.getAttribute("aria-pressed") === "true")).toBe(true);
    expect(screen.getAllByTestId("analytics-point").map(p => [p.getAttribute("cx"), p.getAttribute("cy"), p.getAttribute("r")])).toEqual(coordinates);
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
    expect(a).toHaveAccessibleName(/SOT \/match: 0 ‡; SDP \/ marked FPL xG \/match: 2 \[FPL\]/);
    const defence = screen.getByRole("article", { name: "Defence plot panel" });
    expect(within(defence).queryByTestId("analytics-point")).not.toBeInTheDocument();
    expect(within(defence).getByRole("status")).toHaveTextContent("Missing observations remain unavailable");
    expect(JSON.stringify(props)).toBe(original);
  });

  it("keeps the complete-pair league benchmark cohort when visible clubs are filtered out", () => {
    const props = inputs(); const { rerender } = render(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByText(/League median: 1 eligible clubs/, { selector: "p" })).toHaveLength(2);
    rerender(<SdpFplContextPlots {...props} teams={[]} />);
    expect(screen.getAllByText(/0\/0 visible clubs.*League median: 1 eligible clubs/, { selector: "p" })).toHaveLength(2);
    expect(screen.queryByTestId("analytics-point")).not.toBeInTheDocument();
    rerender(<SdpFplContextPlots {...props} />);
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);
  });
});
