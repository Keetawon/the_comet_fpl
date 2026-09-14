import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadSdpStats } from "@/data/sdpStats";
import { fplSupplement, sdpFixture, sdpMatch, shooting } from "@/test/sdpFixture";
import { sdpCsv, selectSdpEntities } from "@/lib/sdpStats";
import { TeamSdpStatsPage } from "./SdpStatsPage";

vi.mock("@/data/sdpStats", async importOriginal => ({ ...await importOriginal<object>(), loadSdpStats: vi.fn() }));
beforeEach(() => { vi.mocked(loadSdpStats).mockResolvedValue(sdpFixture()); });
const table = () => screen.findByRole("table", { name: "Observed SDP team statistics" });

describe("SDP football observatory", () => {
  it("shows observed open-play averages and honest unavailable set pieces in the table and CSV", async () => {
    const data = sdpFixture();
    const open = { ...shooting, key: "open_play_goals", label: "Open-play goals", provider_field: "goalsOpenplay", verified_semantics: false };
    const setPiece = { ...open, key: "set_piece_goals", label: "Set-piece goals", provider_field: null, description: "Unavailable: no verified total set-piece-goals field." };
    data.metrics = [shooting, open, setPiece];
    data.team_matches = [
      sdpMatch({ sdp: { shots: 10, open_play_goals: 3, set_piece_goals: null } }),
      sdpMatch({ fixture: 2, gw: 2, kickoff_time: "2026-08-29T14:00:00Z", was_home: false, sdp: { shots: 12, open_play_goals: 0, set_piece_goals: null } }),
    ];
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    fireEvent.click(screen.getByRole("button", { name: "Attacking" }));
    expect(within(grid).getByRole("button", { name: "Set-piece goals /match" })).toHaveAttribute("title", expect.stringContaining(setPiece.description));
    expect(within(grid).getByText("1.5")).toHaveTextContent("1.5");
    expect(within(grid).getByText("Unavailable", { selector: "span" }).parentElement).toHaveAttribute("title", expect.stringContaining(setPiece.description));
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:export");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Export filtered CSV" }));
    const csv = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result as string); reader.readAsText(create.mock.calls[0][0] as Blob); });
    create.mockRestore(); revoke.mockRestore(); click.mockRestore();
    expect(csv).toContain("Open-play goals [average per match]");
    expect(csv).toContain('"1.5","2/2",""');
    expect(csv).toContain(`"","0/2","${setPiece.description}"`);
    fireEvent.change(screen.getByRole("combobox", { name: "Venue" }), { target: { value: "away" } });
    expect(within(grid).getByText("0")).toBeInTheDocument();
  });
  it("places the themed plots after the table and shares venue, mode and club selection", async () => {
    const data = sdpFixture();
    data.metrics.push(...["shots_on_target", "shots_on_target_allowed"].map(key => ({ ...shooting, key, label: key })));
    data.team_matches.forEach(row => { row.sdp.shots_on_target = row.was_home ? 2 : 6; row.sdp.shots_on_target_allowed = row.was_home ? 1 : 3; });
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    const plots = screen.getByRole("region", { name: "Attack and defence FPL context" });
    expect(grid.compareDocumentPosition(plots) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const defence = within(plots).getByRole("article", { name: "Defence plot panel" });
    fireEvent.click(within(defence).getByRole("button", { name: /^Chelsea;/ }));
    expect(within(plots).getAllByRole("button", { name: /^Chelsea;/ }).every(p => p.getAttribute("aria-pressed") === "true")).toBe(true);
    expect(screen.getByRole("region", { name: "Chelsea profile" })).toBeInTheDocument();
    const values = within(plots).getAllByTestId("analytics-point").map(p => p.getAttribute("aria-label"));
    fireEvent.change(screen.getByRole("combobox", { name: "Display" }), { target: { value: "total" } });
    expect(within(plots).getAllByTestId("analytics-point").map(p => p.getAttribute("aria-label"))).toEqual(values);
    fireEvent.change(screen.getByRole("combobox", { name: "Venue" }), { target: { value: "home" } });
    expect(within(defence).getByRole("button", { name: /^Chelsea;/ })).toHaveAccessibleName(/SOT conceded \/match: 1;/);
    fireEvent.change(screen.getByRole("textbox", { name: "Search clubs" }), { target: { value: "Chelsea" } });
    expect(within(plots).getAllByTestId("analytics-point")).toHaveLength(2);
    expect(within(plots).getAllByText(/League median: 4 eligible clubs/, { selector: "p" })).toHaveLength(2);
  });
  it("adds percentage-only shot shares in Attacking and keeps them aligned with filters and fullscreen", async () => {
    const data = sdpFixture();
    data.metrics = [shooting, ...["shots_on_target", "shots_inside_box", "shots_outside_box", "shots_blocked"].map(key => ({ ...shooting, key, label: key }))];
    data.team_matches = [
      sdpMatch({ sdp: { shots: 4, shots_on_target: 2, shots_inside_box: 2, shots_outside_box: 2, shots_blocked: 0 } }),
      sdpMatch({ fixture: 2, gw: 2, kickoff_time: "2026-08-29T14:00:00Z", was_home: false, sdp: { shots: 16, shots_on_target: 2, shots_inside_box: 14, shots_outside_box: 2, shots_blocked: 3 } }),
    ];
    const before = JSON.stringify(data);
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    expect(within(grid).queryByText(/\(\d+%\)/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Attacking" }));
    expect(within(grid).getAllByText("(20%)")).toHaveLength(2);
    expect(within(grid).getByText("(80%)").parentElement).toHaveTextContent("8 (80%)");
    expect(within(grid).getByText("(15%)").parentElement).toHaveTextContent("1.5 (15%)");
    fireEvent.change(screen.getByRole("combobox", { name: "Display" }), { target: { value: "total" } });
    expect(within(grid).getByText("(80%)").parentElement).toHaveTextContent("16 (80%)");
    fireEvent.change(screen.getByRole("combobox", { name: "Venue" }), { target: { value: "home" } });
    expect(within(grid).getAllByText("(50%)")).toHaveLength(3);
    expect(within(grid).getByText("(0%)").parentElement).toHaveTextContent("0 (0%)");
    fireEvent.click(screen.getByRole("button", { name: "Enter SDP team statistics table fullscreen" }));
    expect(within(await screen.findByRole("dialog")).getAllByText("(50%)")).toHaveLength(3);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(within(grid).queryByText(/\(\d+%\)/)).not.toBeInTheDocument();
    expect(JSON.stringify(data)).toBe(before);
  });
  it("labels FPL-derived historical xG in the table, trend, scatter and match log without upgrading SDP health", async () => {
    const data = sdpFixture();
    data.team_matches.forEach(row => {
      row.season = "2023-24"; row.status = "UNAVAILABLE"; row.dashboard_status = "INCOMPLETE";
      row.sdp.expected_goals = null;
      row.display_supplements = { expected_goals: fplSupplement(row, 2) };
    });
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    expect(screen.getByText("FPL xG supplement")).toBeInTheDocument();
    expect(within(grid).getAllByLabelText("FPL archive xG supplement")).toHaveLength(4);
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(4);
    expect(screen.getAllByTitle(/FPL archive player-sum xG/).length).toBeGreaterThan(4);
    expect(screen.getByLabelText("Dashboard validation breakdown")).toHaveTextContent("0 dashboard-ready fixtures");
    fireEvent.click(within(grid).getByRole("button", { name: "View Arsenal match detail" }));
    const log = screen.getByRole("table", { name: "Arsenal observed match log" });
    expect(within(log).getAllByLabelText("FPL archive xG supplement")).toHaveLength(5);
    expect(within(log).getAllByText("Incomplete")).toHaveLength(5);
  });
  it("shows retained historical measured fields even when core xG coverage is incomplete", async () => {
    const data = sdpFixture();
    data.team_matches = data.team_matches.map(row => ({ ...row, season: "2025-26", status: "UNAVAILABLE", dashboard_status: "INCOMPLETE", sdp: { ...row.sdp, expected_goals: null } }));
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    expect(screen.getByText(/Some matches lack required SDP fields/)).toBeInTheDocument();
    expect(screen.getByText(/No clubs have complete xG and opponent xG/)).toBeInTheDocument();
    expect(within(grid).getAllByRole("row")).toHaveLength(5);
    expect(within(grid).getAllByTitle(/No measured xg in this range/)).toHaveLength(4);
    fireEvent.click(within(grid).getByRole("button", { name: "View Arsenal match detail" }));
    expect(within(screen.getByRole("table", { name: "Arsenal observed match log" })).getAllByText("Incomplete")).toHaveLength(5);
  });

  it("shows league context without letting a search or club selection redefine percentiles", async () => {
    render(<TeamSdpStatsPage />); await table();
    expect(screen.getByRole("heading", { name: "Team stat from SDP" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Attack meets defence/ })).toBeInTheDocument();
    expect(screen.getAllByTestId("analytics-point-label").map(label => label.textContent)).toEqual(["ARS", "BHA", "CHE", "EVE"]);
    const before = screen.getByRole("region", { name: "Arsenal profile" }).textContent;
    fireEvent.change(screen.getByRole("textbox", { name: "Search clubs" }), { target: { value: "Arsenal" } });
    expect(within(await table()).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Arsenal profile" }).textContent).toBe(before);
    fireEvent.change(screen.getByRole("combobox", { name: "Team" }), { target: { value: "1" } });
    expect(screen.getByRole("region", { name: "Arsenal profile" }).textContent).toBe(before);
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
  });

  it("keeps historical xG plots available when an unrelated core statistic is missing", async () => {
    const data = sdpFixture();
    data.team_matches = data.team_matches.map(row => ({ ...row, season: "2025-26", status: "UNAVAILABLE", dashboard_status: "INCOMPLETE", sdp: { ...row.sdp, shots_on_target: null } }));
    const original = JSON.stringify(data);
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); await table();
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(4);
    expect(screen.getAllByTestId("analytics-point-label")).toHaveLength(4);
    expect(screen.getByRole("region", { name: "Arsenal profile" })).toHaveTextContent("observed matches");
    expect(JSON.stringify(data)).toBe(original);
  });

  it("keeps sorting, comparisons, and match logs usable inside fullscreen and after Escape", async () => {
    render(<TeamSdpStatsPage />); const grid = await table();
    fireEvent.click(within(grid).getByRole("button", { name: "Shots /match" }));
    const enter = screen.getByRole("button", { name: "Enter SDP team statistics table fullscreen" });
    enter.focus(); fireEvent.click(enter);
    const expanded = await screen.findByRole("dialog", { name: "SDP team statistics table fullscreen" });
    for (const name of ["Arsenal", "Brighton", "Chelsea"]) fireEvent.click(within(expanded).getByRole("checkbox", { name: `Compare ${name}` }));
    expect(within(expanded).getByRole("checkbox", { name: "Compare Everton" })).toBeDisabled();
    expect(within(expanded).getByRole("region", { name: "Selected comparison" })).toBeInTheDocument();
    fireEvent.click(within(expanded).getByRole("button", { name: "View Arsenal match detail" }));
    expect(within(expanded).getByRole("table", { name: "Arsenal observed match log" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(enter).toHaveFocus();
    expect(within(grid).getByRole("columnheader", { name: "Shots /match" })).toHaveAttribute("aria-sort", "descending");
    expect(screen.getByRole("checkbox", { name: "Compare Arsenal" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Remove Arsenal from comparison" }));
    expect(screen.getByRole("checkbox", { name: "Compare Everton" })).toBeEnabled();
  });

  it("changes metric groups and totals while profiles consistently remain averages", async () => {
    const data = sdpFixture();
    data.metrics.push({ ...data.metrics[0], key: "passes", label: "Passes" });
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    fireEvent.click(screen.getByRole("button", { name: "Build-up" }));
    expect(within(grid).getByRole("columnheader", { name: "Passes /match" })).toBeInTheDocument();
    expect(within(grid).getAllByText("Unavailable")).toHaveLength(4);
    expect(within(grid).queryByRole("columnheader", { name: "Shots /match" })).not.toBeInTheDocument();
    const profile = screen.getByRole("region", { name: "Arsenal profile" }).textContent;
    fireEvent.change(screen.getByRole("combobox", { name: "Display" }), { target: { value: "total" } });
    expect(within(grid).getByRole("columnheader", { name: "Passes" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Arsenal profile" }).textContent).toBe(profile);
    fireEvent.click(screen.getByRole("button", { name: "All metrics" }));
    expect(within(grid).getByRole("columnheader", { name: "Shots" })).toBeInTheDocument();
  });

  it("coordinates venue, recent windows, profiles and logs; reset clears selections", async () => {
    render(<TeamSdpStatsPage />); await table();
    fireEvent.change(screen.getByRole("combobox", { name: "Recent history" }), { target: { value: "3" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Venue" }), { target: { value: "away" } });
    fireEvent.click(screen.getByRole("button", { name: "View Arsenal match detail" }));
    const log = screen.getByRole("table", { name: "Arsenal observed match log" });
    expect(within(log).getAllByRole("row")).toHaveLength(4);
    expect(within(log).getAllByText(/\(A\)/)).toHaveLength(3);
    expect(screen.getByRole("region", { name: "Arsenal profile" })).toHaveTextContent("Selected window equals the full GW range.");
    fireEvent.change(screen.getByRole("combobox", { name: "Trend metric" }), { target: { value: "team:sdp:shots" } });
    expect(within(screen.getByRole("region", { name: "Arsenal match detail" })).getByRole("img", { name: "Arsenal: observed Shots by match" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("combobox", { name: "Recent history" })).toHaveValue("5");
    expect(screen.getByRole("combobox", { name: "Venue" })).toHaveValue("all");
    expect(screen.queryByRole("table", { name: "Arsenal observed match log" })).not.toBeInTheDocument();
  });

  it("preserves corrected zeros, raw NULL and separate provider/dashboard validity", async () => {
    const data = sdpFixture(); const row = data.team_matches[0];
    row.status = "UNAVAILABLE"; row.dashboard_status = "OWNER_CONFIRMED_VALID";
    const m = { ...data.metrics[0], key: "shots_on_target", label: "Shots on target" }; data.metrics.push(m);
    row.sdp.shots_on_target = null;
    row.display_corrections = { shots_on_target: { correction_id: "owner-sot", value: 0, evidence_class: "owner_confirmed_display_correction", owner_confirmation_recorded_at: "2026-09-08T07:00:00Z", source_known_at: row.known_at, provider_match_id: 123, provider_field: "ontargetScoringAtt", provider_field_state: "omitted", raw_payload_sha256: "a".repeat(64), corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero", relation: "direct", subject_team_code: row.team_code } };
    data.team_matches = [row, { ...row, team_code: row.opponent_team_code, team_name: "Opponent", team_short_name: "OPP", opponent_team_code: row.team_code, was_home: !row.was_home }];
    const before = JSON.stringify(data);
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />); const grid = await table();
    expect(screen.getByText("Dashboard-ready fixtures").parentElement).toHaveTextContent("1 / 1");
    const marker = within(grid).getAllByLabelText("owner-confirmed display correction")[0];
    expect(marker.parentElement).toHaveTextContent(/^0/);
    expect(marker.parentElement).toHaveAttribute("title", expect.stringContaining("raw SDP ontargetScoringAtt was omitted"));
    fireEvent.click(screen.getByRole("button", { name: "View Arsenal match detail" }));
    expect(screen.getByText("Valid · owner-confirmed")).toBeInTheDocument();
    expect(JSON.stringify(data)).toBe(before);
    expect(screen.getByLabelText("Dashboard validation breakdown")).toHaveTextContent("0 from complete SDP + 1 validated with owner-confirmed zeros");
  });

  it("exports the same filtered, sorted observations with the existing CSV provenance", async () => {
    const data = sdpFixture(); render(<TeamSdpStatsPage />); await table();
    fireEvent.change(screen.getByRole("textbox", { name: "Search clubs" }), { target: { value: "Arsenal" } });
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:export");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Export filtered CSV" }));
    const blob = create.mock.calls[0][0] as Blob;
    const rows = selectSdpEntities(data.team_matches, "team", { season: "2026-27", from: 1, to: 6, team: "all", search: "Arsenal", venue: "all", recent: "5", position: "all", minMinutes: 0 });
    const expected = sdpCsv(rows, data.metrics.filter(m => m.scope === "team"), "per_match");
    const text = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result as string); reader.readAsText(blob); });
    expect(text).toBe(expected); expect(click).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith("blob:export");
    create.mockRestore(); revoke.mockRestore(); click.mockRestore();
  });

  it("labels official multi-GW counts, partial GWs and independent forecast vintages", async () => {
    const data = sdpFixture(); data.gameweeks = [1, 2, 3].map(gw => ({ season: "2026-27", gw, finished: true, fixtures_total: 10, fixtures_completed: 10, source_known_at: data.as_of }));
    vi.mocked(loadSdpStats).mockResolvedValue(data); render(<TeamSdpStatsPage />); await table();
    expect(screen.getByText("30 across GW1–GW3")).toBeInTheDocument();
    expect(screen.getByText(/refreshing these statistics does not refresh or relabel those predictions/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Player statistics|Explore individual players/ }).every(link => link.getAttribute("href") === "#players")).toBe(true);
  });

  it("handles unavailable data, empty filters and repeat renders deterministically", async () => {
    vi.mocked(loadSdpStats).mockRejectedValueOnce(new Error("SDP sidecar unavailable"));
    render(<TeamSdpStatsPage />); expect(await screen.findByRole("alert")).toHaveTextContent("SDP sidecar unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry source data" })); const grid = await table();
    const original = grid.textContent;
    fireEvent.change(screen.getByRole("textbox", { name: "Search clubs" }), { target: { value: "absent" } });
    expect(screen.getByRole("button", { name: "Export filtered CSV" })).toBeDisabled();
    expect(within(grid).getByText(/No observed records/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" })); expect(grid.textContent).toBe(original);
    expect(screen.getByRole("combobox", { name: "GW to" })).toHaveTextContent("GW6 · in progress");
  });
});
