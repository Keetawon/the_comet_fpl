import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadSdpStats } from "@/data/sdpStats";
import { sdpFixture } from "@/test/sdpFixture";
import { PlayerSdpStatsPage, TeamSdpStatsPage } from "./SdpStatsPage";

vi.mock("@/data/sdpStats", async importOriginal => ({ ...await importOriginal<object>(), loadSdpStats: vi.fn() }));
beforeEach(() => { vi.mocked(loadSdpStats).mockResolvedValue(sdpFixture()); });

describe("Observed SDP dashboard tabs", () => {
  it("exposes passing and defence groups and says Unavailable for missing values", async () => {
    const data = sdpFixture();
    data.metrics.push({ ...data.metrics[0], key: "passes", label: "Passes", group: "passing" });
    data.metrics.push({ ...data.metrics[0], key: "tackles", label: "Tackles", group: "defence" });
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed SDP team statistics" });
    expect(within(table).getByRole("columnheader", { name: "Passes" })).toBeInTheDocument();
    expect(within(table).getAllByText("Unavailable").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "passing" }));
    expect(screen.getByRole("combobox", { name: "Metric group" })).toHaveValue("passing");
    expect(within(table).queryByRole("columnheader", { name: "Shots" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "defence" }));
    expect(within(table).getByRole("columnheader", { name: "Tackles" })).toBeInTheDocument();
  });
  it("renders the exact team title, observed source scope, sortable table and labelled scatter", async () => {
    render(<TeamSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed SDP team statistics" });
    expect(screen.getByRole("heading", { name: "Team stat from SDP" })).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(screen.getByRole("group", { name: /Observed attack and defence/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: "Shots" }));
    expect(within(table).getByRole("columnheader", { name: "Shots" })).toHaveAttribute("aria-sort", "descending");
  });
  it("labels completed fixtures across gameweeks and keeps observed-data freshness separate", async () => {
    const data = sdpFixture();
    data.gameweeks = [1, 2, 3].map(gw => ({
      season: "2026-27",
      gw,
      finished: true,
      fixtures_total: 10,
      fixtures_completed: 10,
      source_known_at: "2026-09-07T09:00:00+00:00",
    }));
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />);
    await screen.findByRole("table", { name: "Observed SDP team statistics" });
    expect(screen.getByText("Official completed fixtures")).toBeInTheDocument();
    expect(screen.getByText("30 across GW1-GW3")).toBeInTheDocument();
    expect(screen.getByText(/refreshing these statistics does not refresh or relabel those predictions/i)).toBeInTheDocument();
  });
  it("labels owner-confirmed team display corrections without relabelling provider validity", async () => {
    const data = sdpFixture();
    const metric = { ...data.metrics[0], key: "shots_on_target", label: "Shots on target" };
    data.metrics.push(metric);
    const row = data.team_matches.find(item => item.team_code === 1 && item.gw === 6)!;
    row.status = "UNAVAILABLE";
    row.sdp.shots_on_target = null;
    row.display_corrections = {
      shots_on_target: {
        correction_id: "2026-27-f6-team-1-sot",
        value: 0,
        evidence_class: "owner_confirmed_display_correction",
        owner_confirmation_recorded_at: "2026-09-08T07:00:00+00:00",
        source_known_at: "2026-09-07T07:00:00+00:00",
        provider_match_id: 123,
        provider_field: "ontargetScoringAtt",
        provider_field_state: "omitted",
        raw_payload_sha256: "a".repeat(64),
        corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero",
        relation: "direct",
        subject_team_code: 1,
      },
    };
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />);
    await screen.findByRole("table", { name: "Observed SDP team statistics" });
    expect(screen.getByText(/1 owner-confirmed display correction is active/i)).toBeInTheDocument();
    expect(screen.getByText(/provider core validity is unchanged/i)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "GW from" }), { target: { value: "6" } });
    expect(screen.getAllByLabelText("owner-confirmed display correction").length).toBeGreaterThan(0);
  });
  it("searches, filters history and resets all selection state", async () => {
    render(<TeamSdpStatsPage />);
    await screen.findByRole("table", { name: "Observed SDP team statistics" });
    fireEvent.change(screen.getByRole("textbox", { name: "Search clubs" }), { target: { value: "Arsenal" } });
    expect(screen.queryByRole("button", { name: "View Chelsea match detail" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Recent history" }), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "View Arsenal match detail" }));
    const log = screen.getByRole("table", { name: "Arsenal observed match log" });
    expect(within(log).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByRole("img", { name: /Arsenal: observed/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("textbox", { name: "Search clubs" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Recent history" })).toHaveValue("5");
    expect(screen.queryByRole("table", { name: "Arsenal observed match log" })).not.toBeInTheDocument();
  });
  it("limits comparisons to three with a complete exact-value table", async () => {
    render(<TeamSdpStatsPage />);
    await screen.findByRole("table", { name: "Observed SDP team statistics" });
    for (const club of ["Arsenal", "Brighton", "Chelsea"]) fireEvent.click(screen.getByRole("checkbox", { name: `Compare ${club}` }));
    expect(screen.getByRole("checkbox", { name: "Compare Everton" })).toBeDisabled();
    expect(screen.getByRole("table", { name: "Exact comparison values" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Arsenal from comparison" }));
    expect(screen.getByRole("checkbox", { name: "Compare Everton" })).toBeEnabled();
  });
  it("labels unavailable player SDP stats and FPL enrichment without inventing player shots", async () => {
    render(<PlayerSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed player statistics by source" });
    expect(screen.getByRole("heading", { name: "Players stat from SDP" })).toBeInTheDocument();
    expect(screen.getByText("Detailed SDP player statistics are unavailable.")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "FPL · xG" })).toBeInTheDocument();
    expect(within(table).queryByRole("columnheader", { name: /Shots/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Display" }), { target: { value: "per90" } });
    expect(within(table).getByRole("columnheader", { name: "FPL · xG /90" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "FPL position" }), { target: { value: "DEF" } });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
  });
  it("provides a truthful unavailable state and working retry without forecast dependencies", async () => {
    vi.mocked(loadSdpStats).mockRejectedValueOnce(new Error("SDP sidecar unavailable"));
    render(<TeamSdpStatsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("SDP sidecar unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Retry source data" }));
    expect(await screen.findByRole("table", { name: "Observed SDP team statistics" })).toBeInTheDocument();
  });
  it("keeps exposure warnings and official incomplete gameweeks explicit", async () => {
    render(<PlayerSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed player statistics by source" });
    expect(within(table).getAllByText("Low exposure")).toHaveLength(4);
    expect(within(screen.getByRole("combobox", { name: "GW to" })).getByRole("option", { name: "GW6 · in progress" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "GW to" }), { target: { value: "1" } });
    expect(within(table).getAllByText("Very low exposure")).toHaveLength(4);
    expect(screen.getByRole("combobox", { name: "Recent history" })).toHaveClass("min-w-0", "w-full");
    expect(screen.getByRole("combobox", { name: "Team" })).toHaveClass("min-w-0", "w-full");
  });
  it("keeps exact negative recorded points in comparison and missing minutes unknown", async () => {
    const data = sdpFixture();
    data.metrics.push({ ...data.metrics[3], key: "total_points_as_recorded", label: "Recorded points" });
    for (const row of data.player_matches) {
      row.fpl!.total_points_as_recorded = -1;
      if (row.code === 100) row.minutes_fpl = null;
    }
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<PlayerSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed player statistics by source" });
    expect(within(table).getByText("Exposure unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Compare Player 1" }));
    const comparison = screen.getByRole("region", { name: "Selected comparison" });
    expect(within(comparison).getAllByText("-5").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("combobox", { name: "Display" }), { target: { value: "per90" } });
    expect(within(comparison).queryByText("-5")).not.toBeInTheDocument();
  });
  it("shows measured provider fields with their unreconciled qualifier without altering the flag", async () => {
    const data = sdpFixture();
    data.metrics[0].verified_semantics = false;
    data.metrics[0].provider_field = "totalScoringAtt";
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<TeamSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed SDP team statistics" });
    const heading = within(table).getByRole("button", { name: "Shots †" });
    expect(heading).toHaveAttribute("title", expect.stringContaining("totalScoringAtt. Provider observation; not independently reconciled"));
    expect(within(table).getAllByTitle(/totalScoringAtt.*5\/5 matches displayed/)).toHaveLength(4);
    expect(within(table).getAllByTitle(/totalScoringAtt.*5\/5 matches displayed/)[0]).not.toHaveTextContent("—");
    expect(data.metrics[0].verified_semantics).toBe(false);
    expect(screen.getByRole("group", { name: /Observed attack and defence/ })).toBeInTheDocument();
  });
  it("counts measured FPL appearances separately from fixture records and preserves missing exposure", async () => {
    const data = sdpFixture();
    data.player_matches.find(row => row.code === 100 && row.gw === 6)!.minutes_fpl = 0;
    data.player_matches.find(row => row.code === 101 && row.gw === 6)!.minutes_fpl = null;
    vi.mocked(loadSdpStats).mockResolvedValue(data);
    render(<PlayerSdpStatsPage />);
    const table = await screen.findByRole("table", { name: "Observed player statistics by source" });
    const headers = within(table).getAllByRole("columnheader");
    const column = (name: string) => headers.findIndex(head => head.textContent === name);
    const cells = (name: string) => within(within(table).getByRole("button", { name: `View ${name} match detail` }).closest("tr")!).getAllByRole("cell");
    expect(cells("Player 1")[column("FPL appearances")]).toHaveTextContent(/^4$/);
    expect(cells("Player 1")[column("Matches")]).toHaveTextContent(/^5$/);
    expect(cells("Player 1")[column("SDP starts")]).toHaveTextContent(/^5$/);
    expect(cells("Player 2")[column("FPL appearances")]).toHaveTextContent(/^—$/);
  });
});
