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

async function ready() { return screen.findByRole("article", { name: "Gameweek briefing text" }); }
function startEdit(value = "Alpha 2–2 Beta: my proposed scoreline.") {
  fireEvent.click(screen.getByRole("checkbox", { name: "Edit draft" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Briefing draft text" }), { target: { value } });
}
function review() {
  fireEvent.change(screen.getByRole("textbox", { name: "Edit reason (required before sharing)" }), { target: { value: "Added my own match commentary" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "I reviewed this editorial draft" }));
}

it("opens one Thai text post for the summary's exact run and actual GW keys, then changes language and scope", async () => {
  render(<GwAnalysisPage />);
  const article = await ready();
  expect(article).toHaveAttribute("lang", "th");
  expect(article).toHaveTextContent("สรุป GW5");
  expect(screen.getByRole("combobox", { name: "Forecast record" })).toHaveValue("latest-record");
  const gw = screen.getByRole("combobox", { name: "Gameweek" });
  expect(within(gw).getAllByRole("option").map(option => option.textContent)).toEqual(["GW5", "GW7"]);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Preview .*fixture/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(await ready()).toHaveTextContent("GW5 | THE COMET FPL");
  expect(await ready()).toHaveTextContent("1/2 fixtures match");
  expect(await ready()).toHaveTextContent("1.80");
  fireEvent.change(gw, { target: { value: "7" } });
  expect(await ready()).toHaveTextContent("GW7 | THE COMET FPL");
  expect(await ready()).toHaveTextContent("2.60");
  fireEvent.change(screen.getByRole("combobox", { name: "Forecast record" }), { target: { value: "old-record" } });
  expect(await ready()).toHaveTextContent("GW3 | THE COMET FPL");
  expect(screen.getByRole("combobox", { name: "Gameweek" })).toHaveValue("3");
  expect(fetchInsightStatus).not.toHaveBeenCalled();
  expect(fetchInsightSummary).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("keeps a copyable fact draft without optional statistics and falls back to the last data run if summary fails", async () => {
  vi.mocked(loadSummary).mockRejectedValue(new Error("No summary"));
  render(<GwAnalysisPage />);
  await ready();
  expect(screen.getByRole("combobox", { name: "Forecast record" })).toHaveValue("old-record");
  expect(screen.getByText(/Observed statistics unavailable; the post keeps/)).toBeInTheDocument();
  expect(screen.getByText("Published fact draft")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
  const fullText = (await ready()).textContent;
  fireEvent.click(screen.getByRole("button", { name: "Copy" }));
  await waitFor(() => expect(copyGwBriefing).toHaveBeenCalledWith(fullText));
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  await waitFor(() => expect(shareGwBriefing).toHaveBeenCalledWith(fullText));
});

it("requires an edit reason and owner review, stamps editorial opinion, and revokes review on subsequent text or reason edits", async () => {
  const storage = vi.spyOn(Storage.prototype, "setItem");
  render(<GwAnalysisPage />); await ready();
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  startEdit();
  expect(screen.getByText("Editorial analysis · pending owner review")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Download TXT" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "LINE" })).toBeDisabled();
  const reviewed = screen.getByRole("checkbox", { name: "I reviewed this editorial draft" });
  expect(reviewed).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Edit reason (required before sharing)" }), { target: { value: "Added my own match commentary" } });
  expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
  fireEvent.click(reviewed);
  expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Edit draft" }));
  const fullText = (await ready()).textContent;
  expect(fullText).toContain("Alpha 2–2 Beta");
  expect(fullText).toContain("Edited at: 2026-09-19T10:00:00.000Z");
  expect(fullText).toContain("Owner-reviewed at: 2026-09-19T10:00:00.000Z");
  expect(fullText).toContain("Reason: Added my own match commentary");
  expect(fullText).toContain("editorial opinion, separate from the published model forecast");
  expect(fullText).toContain("Source context: 2026-27 GW5");
  expect(fullText).toContain("Forecast record: latest-record · cutoff 2026-09-18 08:00 UTC");
  expect(fullText).toContain("Observed statistics publication: Unavailable");
  expect(fullText).toContain("https://www.thecometfpl.com/");
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  await waitFor(() => expect(shareGwBriefing).toHaveBeenCalledWith(fullText));
  fireEvent.click(screen.getByRole("checkbox", { name: "Edit draft" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Briefing draft text" }), { target: { value: "Alpha 1–1 Beta: updated opinion." } });
  expect(reviewed).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
  fireEvent.click(reviewed);
  fireEvent.change(screen.getByRole("textbox", { name: "Edit reason (required before sharing)" }), { target: { value: "Updated my own commentary" } });
  expect(reviewed).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Copy for Facebook" })).toBeDisabled();
  expect(storage).not.toHaveBeenCalled();
});

it("resets the editorial text, reason and review back to the current published fact draft", async () => {
  render(<GwAnalysisPage />);
  const baseline = (await ready()).textContent;
  startEdit(); review();
  fireEvent.click(screen.getByRole("button", { name: "Reset draft" }));
  expect((await ready()).textContent).toBe(baseline);
  expect(screen.getByRole("checkbox", { name: "Edit draft" })).not.toBeChecked();
  expect(screen.queryByRole("textbox", { name: "Edit reason (required before sharing)" })).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: "I reviewed this editorial draft" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy" })).toBeEnabled();
});

it.each(["GW", "forecast", "language"])("resets local edits and review when %s changes", async scope => {
  render(<GwAnalysisPage />); await ready(); startEdit(); review();
  if (scope === "GW") fireEvent.change(screen.getByRole("combobox", { name: "Gameweek" }), { target: { value: "7" } });
  else if (scope === "forecast") fireEvent.change(screen.getByRole("combobox", { name: "Forecast record" }), { target: { value: "old-record" } });
  else fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(await ready()).not.toHaveTextContent("my proposed scoreline");
  expect(screen.getByRole("checkbox", { name: "Edit draft" })).not.toBeChecked();
  expect(screen.queryByRole("checkbox", { name: "I reviewed this editorial draft" })).not.toBeInTheDocument();
  expect(screen.getByText("Published fact draft")).toBeInTheDocument();
});

it("copies before offering the Facebook link and downloads the complete visible post without opening a popup", async () => {
  const open = vi.spyOn(window, "open");
  render(<GwAnalysisPage />);
  const fullText = (await ready()).textContent;
  fireEvent.click(screen.getByRole("button", { name: "Copy for Facebook" }));
  const link = await screen.findByRole("link", { name: "Open Facebook and paste" });
  expect(prepareGwBriefingFacebook).toHaveBeenCalledWith(fullText);
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.getByText("Briefing copied. Paste the text into Facebook.")).toBeInTheDocument();
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Download TXT" }));
  expect(downloadGwBriefing).toHaveBeenCalledWith(fullText);
});

it("keeps the full editorial text when its LINE URL is too long and reports sharing failures inline", async () => {
  render(<GwAnalysisPage />); await ready();
  startEdit("ก".repeat(1_000)); review();
  expect(screen.getByRole("button", { name: "LINE" })).toBeDisabled();
  expect(screen.getByText(/too long for the LINE link/)).toBeInTheDocument();
  vi.mocked(copyGwBriefing).mockRejectedValueOnce(new Error("Copy denied. Download the text instead."));
  fireEvent.click(screen.getByRole("button", { name: "Copy" }));
  expect(await screen.findByText("Copy denied. Download the text instead.")).toBeInTheDocument();
  expect(vi.mocked(copyGwBriefing).mock.calls.at(-1)?.[0]).toContain("ก".repeat(1_000));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps the forecast load failure separate from optional statistics and offers no invented post", async () => {
  vi.mocked(loadFixtureMatrix).mockRejectedValue(new Error("Missing"));
  render(<GwAnalysisPage />);
  expect(await screen.findByText("Published forecasts are unavailable in this generation.")).toBeInTheDocument();
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy" })).not.toBeInTheDocument();
});
