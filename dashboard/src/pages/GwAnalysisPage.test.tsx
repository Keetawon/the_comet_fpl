import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GwAnalysisPage } from "./GwAnalysisPage";
import { loadFixtureMatrix, loadSummary, type FixtureMatrixData } from "@/data/load";
import { loadSdpStats } from "@/data/sdpStats";
import type { SummaryData, TeamFixture, TeamRecord } from "@/data/types";
import { copyGwBriefing, downloadGwBriefing, prepareGwBriefingFacebook, shareGwBriefing } from "@/lib/gwBriefingShare";
import { fetchInsightStatus, fetchInsightSummary } from "@/lib/planServer";

vi.mock("@/data/load", () => ({ loadFixtureMatrix: vi.fn(), loadSummary: vi.fn() }));
vi.mock("@/data/sdpStats", async original => ({ ...await original<object>(), loadSdpStats: vi.fn() }));
vi.mock("@/lib/planServer", () => ({ fetchInsightStatus: vi.fn(), fetchInsightSummary: vi.fn() }));
vi.mock("@/lib/gwBriefingShare", async original => ({ ...await original<object>(), copyGwBriefing: vi.fn(), shareGwBriefing: vi.fn(),
  prepareGwBriefingFacebook: vi.fn(), downloadGwBriefing: vi.fn() }));

function fixture(id: number, gw: number, home: boolean, mean: number): TeamFixture {
  return { fixture: id, gw, kickoff_time: `2026-09-${gw === 3 ? "12" : gw === 5 ? "20" : "27"}T14:00:00Z`,
    opponent_team_code: home ? 2 : 1, opponent_short_name: home ? "BET" : "ALP", was_home: home, lambda_for: mean, lambda_against: 1.2,
    probability_clean_sheet: 0.3, attack_ease_index: null, defence_ease_index: null, overall_ease_index: null, ease_index_formula_version: "v1", official_fdr: 3,
    stage_a_league_average_team: false };
}
function matrix(): FixtureMatrixData {
  const teams: TeamRecord[] = ["latest-record", "old-record"].flatMap(run_id => [true, false].map(home => ({
    run_id, season: "2026-27", as_of: run_id === "latest-record" ? "2026-09-18T08:00:00Z" : "2026-09-10T08:00:00Z",
    team_code: home ? 1 : 2, team_name: home ? "Alpha" : "Beta", short_name: home ? "ALP" : "BET", form: null,
    fixtures: run_id === "latest-record" ? [fixture(41, 5, home, 1.8), fixture(61, 7, home, 2.6)] : [fixture(11, 3, home, 0.6)],
  })));
  return { teams, manifest: null, easeIndexFormulaVersion: "v1", schedule: { schema_version: 2, semantics: "current_at_export_not_forecast_vintage",
    export_created_at: "2026-09-19T09:00:00Z", database_sha256: "a".repeat(64), teams: [
      { season: "2026-27", team_code: 1, team_name: "Alpha", short_name: "ALP", fixtures: [fixture(41, 5, true, 1.8), fixture(42, 5, true, 1.8), fixture(61, 7, true, 2.6)] },
    ] } };
}
const summary: SummaryData = { latest_run: { run_id: "latest-record", season: "2026-27", as_of: "2026-09-18T08:00:00Z", created_at: null,
  gw_from: 5, gw_to: 7, status: null, component_modes: null }, roster: { players: 0, teams: 2 }, next_gameweek: null,
  top_xp: [], horizon_top_xp: [], flagged_top_xp: [], easiest_fixtures: [], hardest_fixtures: [], optimizer_plans: [], ease_index_formula_version: "v1" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T10:00:00Z"));
  vi.stubGlobal("fetch", vi.fn());
  vi.mocked(loadFixtureMatrix).mockResolvedValue(matrix());
  vi.mocked(loadSummary).mockResolvedValue(summary);
  vi.mocked(loadSdpStats).mockRejectedValue(new Error("Optional statistics absent"));
  vi.mocked(copyGwBriefing).mockResolvedValue(undefined);
  vi.mocked(shareGwBriefing).mockResolvedValue("shared");
  vi.mocked(prepareGwBriefingFacebook).mockResolvedValue({ url: "https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fwww.thecometfpl.com%2F", instruction: "Briefing copied. Paste the text into Facebook." });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function ready() { return screen.findByRole("textbox", { name: "Analysis message" }) as Promise<HTMLTextAreaElement>; }
function sources() { fireEvent.click(screen.getByText("Sources & how to read this")); }

it("shows Score Prediction with unchanged goal averages and team clean-sheet chances, not invented score picks", async () => {
  render(<GwAnalysisPage />);
  const text = await ready();
  expect(screen.getByRole("heading", { name: "Score Prediction" })).toBeInTheDocument();
  expect(text).toHaveAttribute("readonly");
  expect(text).toHaveAttribute("lang", "th");
  expect(text.value).toContain("สรุป GW5");
  expect(text.value).toContain("ปัดค่าเฉลี่ยประตู: ALP 2–2 BET");
  expect(screen.getByText(/Rounded goal averages, with the original estimates/)).toBeInTheDocument();
  const match = screen.getByRole("article", { name: "Alpha v Beta" });
  expect(within(match).getAllByText("(1.80)")).toHaveLength(2);
  expect(within(match).getAllByText("2")).toHaveLength(2);
  expect(within(match).getByRole("group", { name: "Alpha goal outlook" })).toHaveTextContent("Rounded expected goals: 2Published expected goals: (1.80)");
  expect(within(match).getAllByText("30%")).toHaveLength(2);
  expect(screen.queryByRole("checkbox", { name: /Edit|review/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reset draft" })).not.toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: /reason/i })).not.toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Forecast record" }).closest("details")).not.toHaveAttribute("open");
  expect(fetchInsightStatus).not.toHaveBeenCalled();
  expect(fetchInsightSummary).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("selects only actual published GW keys and retains explicit vintage control in details", async () => {
  render(<GwAnalysisPage />); await ready();
  const gw = screen.getByRole("combobox", { name: "Gameweek" });
  expect(within(gw).getAllByRole("option").map(option => option.textContent)).toEqual(["GW5", "GW7"]);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect((await ready()).value).toContain("1/2 fixtures match");
  fireEvent.change(gw, { target: { value: "7" } });
  expect((await ready()).value).toContain("GW7 | THE COMET FPL");
  expect((await ready()).value).toContain("Rounded goal averages: ALP 3–3 BET");
  sources();
  fireEvent.change(screen.getByRole("combobox", { name: "Forecast record" }), { target: { value: "old-record" } });
  expect((await ready()).value).toContain("GW3 | THE COMET FPL");
  expect(gw).toHaveValue("3");
});

it("shares exactly the read-only displayed message without storing user data", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem");
  render(<GwAnalysisPage />);
  const fullText = (await ready()).value;
  fireEvent.click(screen.getByRole("button", { name: "Copy text" }));
  await waitFor(() => expect(copyGwBriefing).toHaveBeenCalledWith(fullText));
  expect(await screen.findByRole("button", { name: "Copied" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  await waitFor(() => expect(shareGwBriefing).toHaveBeenCalledWith(fullText));
  expect(storage).not.toHaveBeenCalled();
});

it("clears old copy/share feedback when language or GW changes", async () => {
  render(<GwAnalysisPage />); await ready();
  fireEvent.click(screen.getByRole("button", { name: "Copy text" }));
  await screen.findByRole("button", { name: "Copied" });
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("button", { name: "Copy text" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Copied" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Gameweek" }), { target: { value: "7" } });
  expect((await ready()).value).toContain("GW7");
});

it("copies before offering a Facebook link and downloads the whole post without a popup", async () => {
  const open = vi.spyOn(window, "open");
  render(<GwAnalysisPage />);
  const fullText = (await ready()).value;
  fireEvent.click(screen.getByRole("button", { name: "Copy for Facebook" }));
  expect(await screen.findByRole("link", { name: "Open Facebook and paste" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(prepareGwBriefingFacebook).toHaveBeenCalledWith(fullText);
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "TXT" }));
  expect(downloadGwBriefing).toHaveBeenCalledWith(fullText);
});

it("does not fill a missing goal estimate or clean-sheet probability with zero", async () => {
  const data = matrix();
  data.teams[0].fixtures[0].lambda_for = null;
  data.teams[0].fixtures[0].probability_clean_sheet = null;
  vi.mocked(loadFixtureMatrix).mockResolvedValue(data);
  render(<GwAnalysisPage />); await ready();
  const match = screen.getByRole("article", { name: "Alpha v Beta" });
  expect(within(match).getAllByText("—")).toHaveLength(2);
  expect(within(match).queryByText("0%")).not.toBeInTheDocument();
  expect(within(match).queryByText("(0.00)")).not.toBeInTheDocument();
});

it("retains observed zero and the original estimate below the rounded score", async () => {
  const data = matrix();
  data.teams[0].fixtures[0].lambda_for = 0;
  data.teams[1].fixtures[0].lambda_for = 1.77;
  vi.mocked(loadFixtureMatrix).mockResolvedValue(data);
  render(<GwAnalysisPage />); await ready();
  expect(screen.getByRole("group", { name: "Alpha goal outlook" })).toHaveTextContent("Rounded expected goals: 0Published expected goals: (0.00)");
  expect(screen.getByRole("group", { name: "Beta goal outlook" })).toHaveTextContent("Rounded expected goals: 2Published expected goals: (1.77)");
  expect(data.teams[1].fixtures[0].lambda_for).toBe(1.77);
});

it("keeps a usable post without SDP statistics and labels the missing context", async () => {
  vi.mocked(loadSummary).mockRejectedValue(new Error("No summary"));
  render(<GwAnalysisPage />);
  expect((await ready()).value).toContain("GW3");
  expect(screen.getByText(/Recent team statistics are unavailable/)).toBeInTheDocument();
  vi.mocked(copyGwBriefing).mockRejectedValueOnce(new Error("Copy denied. Download the text instead."));
  fireEvent.click(screen.getByRole("button", { name: "Copy text" }));
  expect(await screen.findByText("Copy denied. Download the text instead.")).toBeInTheDocument();
});

it("offers no invented post when the forecast cannot be loaded", async () => {
  vi.mocked(loadFixtureMatrix).mockRejectedValue(new Error("Missing"));
  render(<GwAnalysisPage />);
  expect(await screen.findByText("This matchweek is not available yet")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "Analysis message" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy text" })).not.toBeInTheDocument();
});

it("keeps the DEMO disclosure in copied text even when optional statistics are absent", async () => {
  const data = matrix();
  data.teams.forEach(team => { team.run_id = `DEMO-${team.run_id}`; });
  vi.mocked(loadFixtureMatrix).mockResolvedValue(data);
  render(<GwAnalysisPage />);
  const text = await ready();
  expect(text.value).toMatch(/^DEMO · Synthetic preview only/);
  fireEvent.click(screen.getByRole("button", { name: "Copy text" }));
  await waitFor(() => expect(copyGwBriefing).toHaveBeenCalledWith(text.value));
});

it("does not call pending statistics unavailable or share a briefing that is still loading", async () => {
  let rejectStats!: (error: Error) => void;
  vi.mocked(loadSdpStats).mockReturnValue(new Promise((_resolve, reject) => { rejectStats = reject; }));
  render(<GwAnalysisPage />);
  await screen.findByText(/Loading team statistics for the briefing/);
  expect(screen.queryByText(/Recent team statistics are unavailable/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy text" })).not.toBeInTheDocument();
  rejectStats(new Error("Unavailable"));
  await ready();
  expect(screen.getByRole("button", { name: "Copy text" })).toBeEnabled();
});
