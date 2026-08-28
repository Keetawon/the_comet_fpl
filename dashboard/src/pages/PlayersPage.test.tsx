// Page smoke: the Players pivot renders from a read model without crashing -- one row
// per player of the SELECTED vintage (never one per recorded run), player filters, the
// availability overlay label, per-GW chip columns with blank slots, and expanded rolling
// historical fixture observations across the current and immediately preceding seasons.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw, loadPlayerActuals, loadPlayerHorizons, loadPlayers } from "@/data/load";
import playersSample from "@/data/samplePlayers.json";
import teamsSample from "@/data/sampleFixtureMatrix.json";
import nextGwSample from "@/data/sampleNextGw.json";
import horizonsSample from "@/data/samplePlayerHorizons.json";
import type {
  NextGwPlan,
  PlayerActualFixture,
  PlayerActualsData,
  PlayerFormWindow,
  PlayerHorizonsData,
  PlayerRecord,
  TeamRecord,
} from "@/data/types";
import { PLAYER_HORIZON_FIELDS } from "@/data/types";
import {
  fetchManagerTeamMembers,
  type ManagerTeamPlayer,
  type ManagerTeamPreview,
} from "@/lib/planServer";
import { PlayersPage } from "./PlayersPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];
const horizonsData: PlayerHorizonsData = {
  ...(horizonsSample as unknown as Omit<
    PlayerHorizonsData,
    "horizon_fields" | "players"
  >),
  horizon_fields: PLAYER_HORIZON_FIELDS,
  players: horizonsSample.players.map((player) => ({
    ...player,
    horizons: player.horizons.map(
      ([gw_to, xp, p_le_2, p_ge_2, p_ge_4, p_ge_6, p_ge_10, p_ge_15]) => ({
        gw_to,
        xp,
        p_le_2,
        p_ge_2,
        p_ge_4,
        p_ge_6,
        p_ge_10,
        p_ge_15,
      }),
    ),
  })),
};

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadPlayerActuals: vi.fn(),
  loadPlayerHorizons: vi.fn(),
  loadFixtureMatrix: vi.fn(),
  loadNextGw: vi.fn(),
}));

vi.mock("@/lib/planServer", async () => {
  const actual = await vi.importActual<typeof import("@/lib/planServer")>("@/lib/planServer");
  return { ...actual, fetchManagerTeamMembers: vi.fn() };
});

beforeAll(() => {
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

const teamsForRunA: TeamRecord[] = teamsSample.teams.map((t) => ({ ...t, run_id: "run-a" }));

function actualFromForm(
  form: Partial<PlayerFormWindow>,
  patch: Partial<PlayerActualFixture> = {},
): PlayerActualFixture {
  return {
    gw: 1,
    fixture: 901,
    kickoff_time: "2026-08-22T14:00:00+00:00",
    minutes: form.minutes ?? 90,
    starts: form.starts ?? 1,
    goals_scored: form.goals_scored ?? 0,
    assists: form.assists ?? 0,
    clean_sheets: form.clean_sheets ?? 0,
    goals_conceded: form.goals_conceded ?? 0,
    saves: form.saves ?? 0,
    bonus: form.bonus ?? 0,
    bps: form.bps ?? 0,
    defensive_contribution: form.defensive_contribution ?? 0,
    expected_goals: form.expected_goals ?? null,
    expected_assists: form.expected_assists ?? null,
    expected_goals_conceded: form.expected_goals_conceded ?? null,
    points_under_rules_2026_27: form.points_under_rules_2026_27 ?? null,
    ...patch,
  };
}

type PlayerWithTestActuals = PlayerRecord & { actuals: PlayerActualFixture[] };

const playersWithActuals: PlayerWithTestActuals[] = playersSample.players.map((player, index) => {
  const source = player as unknown as PlayerRecord;
  const form: Partial<PlayerFormWindow> = source.form?.windows.last_5 ?? {};
  return {
    ...source,
    actuals: [
      actualFromForm(form, {
        fixture: 901 + index,
        minutes: index === 0 ? (form.minutes ?? 90) : 0,
        starts: index === 0 ? (form.starts ?? 1) : 0,
      }),
    ],
  };
});

const actualsData: PlayerActualsData = {
  schema: "fpl.dashboard-player-actuals",
  json_schema_version: 8,
  players: playersWithActuals.map((player) => ({
    season: player.season,
    code: player.code,
    actuals: player.actuals,
  })),
};

function managerPreview(players: readonly PlayerRecord[]): ManagerTeamPreview {
  const managerPlayers: ManagerTeamPlayer[] = players.map((player, index) => ({
    element_id: 10_000 + index,
    code: player.code,
    web_name: player.web_name,
    position: player.position as ManagerTeamPlayer["position"],
    team_id: 1,
    team_code: player.team_code,
    now_cost: player.now_cost ?? 0,
    purchase_price: player.now_cost ?? 0,
    selling_price: player.now_cost ?? 0,
  }));
  return {
    capture_id: "manager-capture-1",
    captured_at: "2026-08-27T15:30:00+07:00",
    manager_id: 123456,
    entry_name: "Test XI",
    picks_event: 1,
    planning_gw: 1,
    bank_tenths: 0,
    squad_selling_value_tenths: managerPlayers.reduce(
      (total, player) => total + player.selling_price,
      0,
    ),
    free_transfers_available: 1,
    free_transfers_source: "reconstructed",
    existing_hit_points: 0,
    players: managerPlayers,
  };
}

function managerFilterPlayers(): { squad: PlayerRecord[]; outsider: PlayerRecord } {
  const source = playersWithActuals[0];
  const squad = Array.from({ length: 15 }, (_, index): PlayerRecord => ({
    ...source,
    code: 100 + index,
    web_name: `Squad ${index + 1}`,
    position: index < 5 ? "DEF" : "MID",
    now_cost: 50,
    form: source.form,
  }));
  return {
    squad,
    outsider: {
      ...source,
      code: 999,
      web_name: "Outside Defender",
      position: "DEF",
      now_cost: 50,
      form: source.form,
    },
  };
}

function playerWithLastFive(
  code: number,
  webName: string,
  position: string,
  form: Partial<PlayerFormWindow>,
): PlayerWithTestActuals {
  const source = playersSample.players[0] as unknown as PlayerRecord;
  if (source.form == null) throw new Error("sample player must carry observed form");
  return {
    ...source,
    code,
    web_name: webName,
    position,
    actuals: [actualFromForm({ ...source.form.windows.last_5, ...form }, { fixture: 950 + code })],
    form: {
      ...source.form,
      windows: {
        ...source.form.windows,
        last_5: { ...source.form.windows.last_5, ...form },
      },
    },
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
  vi.mocked(fetchManagerTeamMembers).mockReset();
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersWithActuals, manifest: null });
  vi.mocked(loadPlayerActuals).mockResolvedValue(actualsData);
  vi.mocked(loadPlayerHorizons).mockResolvedValue(
    horizonsData,
  );
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: teamsForRunA,
    schedule: {
      schema_version: 1,
      semantics: "current_at_export_not_forecast_vintage",
      export_created_at: "2026-08-20T00:00:00+00:00",
      database_sha256: "d".repeat(64),
      teams: [],
    },
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("PlayersPage", () => {
  it("renders the pivot: players, form columns, availability overlay, GW chips", async () => {
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const fullscreenButton = screen.getByRole("button", {
      name: "Enter Players table fullscreen",
    });
    expect(fullscreenButton).toBeInTheDocument();
    const tableShell = fullscreenButton.closest("[data-fullscreen-mode]");
    expect(tableShell).not.toBeNull();
    expect(screen.getByRole("region", { name: "Filters" }).nextElementSibling).toBe(
      tableShell,
    );
    expect(screen.getByText("Beta")).toBeInTheDocument();
    const appHeader = screen.getByRole("columnheader", { name: "App" });
    expect(appHeader).toHaveAttribute("title", "Finalized 2026-27 actuals, GW1-GW1");
    expect(screen.getByText("Observed stats")).toBeInTheDocument();
    expect(screen.getByText("2026-27 · GW1")).toBeInTheDocument();
    expect(screen.queryByText("Actual 2026-27 GW1-1 App")).not.toBeInTheDocument();
    expect(screen.getByText("Forecast GWs")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Actual season" })).toHaveTextContent("2026-27");
    expect(screen.getByText("Actual GWs")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Actual from gameweek" })).toHaveTextContent("GW1");
    expect(screen.getByRole("combobox", { name: "Actual to gameweek" })).toHaveTextContent("GW1");
    expect(screen.queryByRole("combobox", { name: "Past form window" })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Forecast GWs filter upcoming fixtures and xP only/),
    ).toHaveTextContent("Min avg min (L5) filter remains its separately published trailing-five anchor");
    expect(screen.getByText(/visible players have finalized 2026-27 observations/)).toBeInTheDocument();
    expect(screen.getByText(/leads measured replayed points in the selected actual range/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /xP GW1-5/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^xP GW1$/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    const visibleHeaders = screen
      .getAllByRole("columnheader")
      .map((header) => header.textContent?.trim());
    expect(visibleHeaders.indexOf("xP GW1")).toBe(visibleHeaders.indexOf("Pts") + 1);
    for (const name of ["P(≤2)", "P(≥2)", "P(≥4)", "P(≥6)", "P(≥10)", "P(≥15)"]) {
      expect(screen.queryByRole("columnheader", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByText(/dense Players table omits the six overlapping/i)).toBeInTheDocument();
    // availability is labelled as the official overlay, never as "starts"
    expect(screen.getAllByText(/doubtful/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("spinbutton", { name: "Minimum price in millions" }),
    ).toBeInTheDocument();
    // one chip per fixture, blank slot for a gameweek with none (GW2 for Beta)
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByTestId("blank-slot").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTitle("Published xP for GW1: 7.4")).toHaveTextContent("7.4");
  });

  it("filters to an exact manager squad by stable code and composes with player filters", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider],
      manifest: null,
    });
    vi.mocked(fetchManagerTeamMembers).mockResolvedValue(managerPreview(squad));

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));

    expect(fetchManagerTeamMembers).toHaveBeenCalledWith("123456", "");
    await waitFor(() => expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument());
    expect(screen.getAllByRole("button", { name: /expand fixtures/i })).toHaveLength(15);
    expect(
      screen.getByText("Verified 15/15 players for Test XI. 15 match the other visible filters."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeDisabled();
    expect(
      screen.getByText(/AI explanation is unavailable while the private My squad filter is active/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Position filter" }));
    await user.click(screen.getByRole("option", { name: "DEF" }));
    expect(screen.getAllByRole("button", { name: /expand fixtures/i })).toHaveLength(5);
    expect(screen.queryByText("Squad 6")).not.toBeInTheDocument();
    expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show all players" }));
    expect(await screen.findByText("Outside Defender")).toBeInTheDocument();
    expect(screen.queryByText("Squad 6")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/AI explanation is unavailable while the private My squad filter is active/),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show my squad" }));
    await waitFor(() => expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Outside Defender")).toBeInTheDocument();
    expect(await screen.findByText("Squad 6")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all players" })).not.toBeInTheDocument();
  });

  it("preserves the active squad when a replacement manager fetch fails", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider],
      manifest: null,
    });
    vi.mocked(fetchManagerTeamMembers)
      .mockResolvedValueOnce(managerPreview(squad))
      .mockRejectedValueOnce(new Error("manager not found"));

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    const managerId = screen.getByLabelText("FPL manager ID");
    await user.type(managerId, "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));
    await waitFor(() => expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument());

    await user.clear(managerId);
    await user.type(managerId, "654321");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "manager not found The verified My squad filter was kept unchanged.",
    );
    expect(screen.getAllByRole("button", { name: /expand fixtures/i })).toHaveLength(15);
    expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument();
    expect(screen.getByText(/Verified 15\/15 players for Test XI/)).toBeInTheDocument();
  });

  it("returns to the first table page when a manager squad narrows a later page", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    const extras = Array.from({ length: 44 }, (_, index): PlayerRecord => ({
      ...outsider,
      code: 1_000 + index,
      web_name: `Extra ${index + 1}`,
    }));
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider, ...extras],
      manifest: null,
    });
    vi.mocked(fetchManagerTeamMembers).mockResolvedValueOnce(managerPreview(squad));

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("1–50 of 60")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("51–60 of 60")).toBeInTheDocument();

    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));

    expect(await screen.findByText("Squad 1")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /expand fixtures/i })).toHaveLength(15);
    expect(screen.queryByText("No players match the current filters.")).not.toBeInTheDocument();
  });

  it("clears the private squad scope when the forecast vintage changes", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    const runBPlayers = [...squad, outsider].map((player) => ({
      ...player,
      run_id: "run-b",
    }));
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider, ...runBPlayers],
      manifest: null,
    });
    vi.mocked(loadPlayerHorizons).mockResolvedValueOnce({
      ...horizonsData,
      players: [
        ...horizonsData.players,
        ...horizonsData.players.map((player) => ({ ...player, run_id: "run-b" })),
      ],
    });
    vi.mocked(fetchManagerTeamMembers).mockResolvedValueOnce(managerPreview(squad));

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));
    await waitFor(() => expect(screen.queryByText("Outside Defender")).not.toBeInTheDocument());

    await user.click(screen.getByRole("combobox", { name: "Forecast vintage" }));
    await user.click(screen.getByRole("option", { name: /run-b/ }));

    expect(await screen.findByText("Outside Defender")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all players" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The My squad filter was cleared because the forecast vintage changed",
    );
  });

  it("ignores a pending manager response after the forecast vintage changes", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    const runBPlayers = [...squad, outsider].map((player) => ({
      ...player,
      run_id: "run-b",
    }));
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider, ...runBPlayers],
      manifest: null,
    });
    vi.mocked(loadPlayerHorizons).mockResolvedValueOnce({
      ...horizonsData,
      players: [
        ...horizonsData.players,
        ...horizonsData.players.map((player) => ({ ...player, run_id: "run-b" })),
      ],
    });
    let resolveManager!: (preview: ManagerTeamPreview) => void;
    vi.mocked(fetchManagerTeamMembers).mockReturnValueOnce(
      new Promise<ManagerTeamPreview>((resolve) => {
        resolveManager = resolve;
      }),
    );

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));
    expect(screen.getByRole("button", { name: "Fetching squad…" })).toBeDisabled();

    await user.click(screen.getByRole("combobox", { name: "Forecast vintage" }));
    await user.click(screen.getByRole("option", { name: /run-b/ }));
    resolveManager(managerPreview(squad));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The My squad filter was cleared because the forecast vintage changed",
      ),
    );
    expect(screen.getByText("Outside Defender")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all players" })).not.toBeInTheDocument();
  });

  it("rejects a partial manager-to-vintage mapping without changing the table", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    const incomplete = managerPreview(squad);
    incomplete.players[14] = {
      ...incomplete.players[14],
      element_id: 99_999,
      code: 99_999,
    };
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider],
      manifest: null,
    });
    vi.mocked(fetchManagerTeamMembers).mockResolvedValueOnce(incomplete);

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "All 15 manager-squad players must match the selected forecast vintage",
    );
    expect(screen.getAllByRole("button", { name: /expand fixtures/i })).toHaveLength(16);
    expect(screen.getByText("Outside Defender")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all players" })).not.toBeInTheDocument();
  });

  it("keeps manager-squad filtering local-only in hosted static builds", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    expect(screen.getByLabelText("FPL manager ID")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Show my squad" })).toBeDisabled();
    expect(
      screen.getByText(/Manager-squad filtering is local-only and requires the trusted Plan Server/),
    ).toBeInTheDocument();
    expect(fetchManagerTeamMembers).not.toHaveBeenCalled();
  });

  it("switches the Players-only observed columns between Overall, Attack, and Defense", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    // Overall is genuinely balanced: common, attack, and defense form are all present.
    for (const name of ["Starts", "G", "xGI", "xG/90", "CS", "GC", "Saves", "DC", "xGC", "BPS/App"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    let headers = screen.getAllByRole("columnheader").map((header) => header.textContent?.trim());
    expect(headers.slice(headers.indexOf("xA"), headers.indexOf("xA") + 3)).toEqual([
      "xA",
      "xGI",
      "xG/90",
    ]);
    expect(screen.getByRole("columnheader", { name: "BPS/App" }).querySelector("span")).toHaveAttribute(
      "title",
      "Average observed BPS per appearance in the selected Actual GWs (total BPS divided by appearances); each played double-gameweek leg counts once and DNPs are excluded",
    );
    expect(
      within(screen.getByText("Alpha").closest("tr")!).getByTitle(
        "Observed BPS per appearance: 90.0 (90 total BPS across 1 appearance)",
      ),
    ).toHaveTextContent("90.0");
    expect(
      within(screen.getByText("Alpha").closest("tr")!).getByTitle(
        "Observed xGI (xG + xA): 2.7",
      ),
    ).toHaveTextContent("2.7");

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    expect(screen.queryByRole("columnheader", { name: "G" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xG/90" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xGI" })).not.toBeInTheDocument();
    for (const name of ["CS", "GC", "Saves", "DC", "xGC", "Bonus", "BPS/App", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("radio", { name: "Attack" }));
    expect(screen.queryByRole("columnheader", { name: "CS" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xGC" })).not.toBeInTheDocument();
    for (const name of ["G", "A", "xG", "xA", "xGI", "xG/90", "xA/90", "Bonus", "BPS/App", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    headers = screen.getAllByRole("columnheader").map((header) => header.textContent?.trim());
    expect(headers.slice(headers.indexOf("xA"), headers.indexOf("xA") + 3)).toEqual([
      "xA",
      "xGI",
      "xG/90",
    ]);
  });

  it("keeps observed xGI measured-zero distinct from a missing xG or xA component", async () => {
    const user = userEvent.setup();
    const players = [
      playerWithLastFive(11, "Zero xGI", "MID", {
        expected_goals: 0,
        expected_assists: 0,
      }),
      playerWithLastFive(12, "Missing xGI", "MID", {
        expected_goals: 0.4,
        expected_assists: null,
      }),
      playerWithLastFive(13, "Positive xGI", "MID", {
        expected_goals: 0.4,
        expected_assists: 0.3,
      }),
    ];
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: players.map((player) => ({
        season: player.season,
        code: player.code,
        actuals: player.actuals,
      })),
    });

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Zero xGI")).toBeInTheDocument());

    expect(
      within(screen.getByText("Zero xGI").closest("tr")!).getByTitle(
        "Observed xGI (xG + xA): 0.0",
      ),
    ).toHaveTextContent("0.0");
    expect(
      within(screen.getByText("Missing xGI").closest("tr")!).getByTitle(
        "xGI is unmeasured because observed xG or xA is unavailable",
      ),
    ).toHaveTextContent("–");
    expect(
      within(screen.getByText("Positive xGI").closest("tr")!).getByTitle(
        "Observed xGI (xG + xA): 0.7",
      ),
    ).toHaveTextContent("0.7");

    const xgiHeader = screen.getByRole("columnheader", { name: "xGI" });
    const table = xgiHeader.closest("table")!;
    const order = () =>
      [...table.querySelectorAll("tbody > tr")]
        .map((row) =>
          ["Zero xGI", "Missing xGI", "Positive xGI"].find((name) =>
            row.textContent?.includes(name),
          ),
        )
        .filter((name): name is string => name != null);

    await user.click(within(xgiHeader).getByRole("button"));
    expect(order()).toEqual(["Positive xGI", "Zero xGI", "Missing xGI"]);
    await user.click(within(xgiHeader).getByRole("button"));
    expect(order()).toEqual(["Zero xGI", "Positive xGI", "Missing xGI"]);
  });

  it("shows and sorts BPS per appearance rather than cumulative BPS", async () => {
    const user = userEvent.setup();
    const highAverage = playerWithLastFive(31, "High average", "MID", {});
    const highTotal = playerWithLastFive(32, "High total", "MID", {});
    const missing = playerWithLastFive(33, "Missing BPS", "MID", {});
    const players = [highAverage, highTotal, missing];
    const actuals = new Map<number, PlayerActualFixture[]>([
      [
        highAverage.code,
        [actualFromForm({}, { fixture: 981, minutes: 90, starts: 1, bps: 30 })],
      ],
      [
        highTotal.code,
        [982, 983, 984, 985].map((fixture) =>
          actualFromForm({}, { fixture, minutes: 90, starts: 1, bps: 10 }),
        ),
      ],
      [
        missing.code,
        [actualFromForm({}, { fixture: 986, minutes: 90, starts: 1, bps: null })],
      ],
    ]);
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: players.map((player) => ({
        season: player.season,
        code: player.code,
        actuals: actuals.get(player.code) ?? [],
      })),
    });

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("High average")).toBeInTheDocument());

    expect(
      within(screen.getByText("High average").closest("tr")!).getByTitle(
        "Observed BPS per appearance: 30.0 (30 total BPS across 1 appearance)",
      ),
    ).toHaveTextContent("30.0");
    expect(
      within(screen.getByText("High total").closest("tr")!).getByTitle(
        "Observed BPS per appearance: 10.0 (40 total BPS across 4 appearances)",
      ),
    ).toHaveTextContent("10.0");
    expect(
      within(screen.getByText("Missing BPS").closest("tr")!).getByTitle(
        "BPS per appearance is unavailable because no complete appeared-fixture BPS evidence exists",
      ),
    ).toHaveTextContent("–");

    const header = screen.getByRole("columnheader", { name: "BPS/App" });
    const table = header.closest("table")!;
    const order = () =>
      [...table.querySelectorAll("tbody > tr")]
        .map((row) =>
          ["High average", "High total", "Missing BPS"].find((name) =>
            row.textContent?.includes(name),
          ),
        )
        .filter((name): name is string => name != null);

    await user.click(within(header).getByRole("button"));
    expect(order()).toEqual(["High average", "High total", "Missing BPS"]);
    await user.click(within(header).getByRole("button"));
    expect(order()).toEqual(["High total", "High average", "Missing BPS"]);
  });

  it("distinguishes measured zero, unmeasured, and position-inapplicable defense form", async () => {
    const user = userEvent.setup();
    const players = [
      playerWithLastFive(11, "Null Defender", "DEF", {
        clean_sheets: 0,
        goals_conceded: 4,
        saves: 0,
        defensive_contribution: 0,
        expected_goals_conceded: null,
      }),
      playerWithLastFive(12, "Keeper", "GK", {
        clean_sheets: 2,
        goals_conceded: 3,
        saves: 12,
        defensive_contribution: 0,
        expected_goals_conceded: 1.2,
      }),
      playerWithLastFive(13, "Measured Defender", "DEF", {
        clean_sheets: 1,
        goals_conceded: 2,
        saves: 0,
        defensive_contribution: 17,
        expected_goals_conceded: 2.4,
      }),
      playerWithLastFive(14, "Midfielder", "MID", {
        clean_sheets: 1,
        goals_conceded: 7,
        saves: 0,
        defensive_contribution: 9,
        expected_goals_conceded: 3.1,
      }),
    ];
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: players.map((player) => ({
        season: player.season,
        code: player.code,
        actuals: player.actuals,
      })),
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Null Defender")).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "Defense" }));

    const nullDefenderRow = screen.getByText("Null Defender").closest("tr")!;
    expect(within(nullDefenderRow).getByTitle("Observed CS: 0")).toHaveTextContent("0");
    expect(within(nullDefenderRow).getByTitle("Saves is not applicable to DEF")).toHaveTextContent(
      "–",
    );
    expect(
      within(nullDefenderRow).getByTitle("xGC is unmeasured in this form window"),
    ).toHaveTextContent("–");
    const keeperRow = screen.getByText("Keeper").closest("tr")!;
    expect(within(keeperRow).getByTitle("Observed GC: 3")).toHaveTextContent("3");
    expect(within(keeperRow).getByTitle("Observed Saves: 12")).toHaveTextContent("12");
    expect(within(keeperRow).getByTitle("Observed xGC: 1.2")).toHaveTextContent("1.2");
    expect(within(keeperRow).getByTitle("DC is not applicable to GK")).toHaveTextContent("–");
    const midfielderRow = screen.getByText("Midfielder").closest("tr")!;
    expect(within(midfielderRow).getByTitle("Observed DC: 9")).toHaveTextContent("9");
    for (const metric of ["GC", "Saves", "xGC"]) {
      expect(
        within(midfielderRow).getByTitle(`${metric} is not applicable to MID`),
      ).toHaveTextContent("–");
    }

    // Undefined/inapplicable values stay last in either sort direction.
    const xgc = screen.getByRole("columnheader", { name: "xGC" });
    const table = xgc.closest("table")!;
    const order = () =>
      [...table.querySelectorAll("tbody > tr")]
        .map((row) =>
          ["Null Defender", "Keeper", "Measured Defender", "Midfielder"].find((name) =>
            row.textContent?.includes(name),
          ),
        )
        .filter((name): name is string => name != null);
    await user.click(within(xgc).getByRole("button"));
    const firstDirection = order();
    expect(new Set(firstDirection.slice(-2))).toEqual(new Set(["Null Defender", "Midfielder"]));
    await user.click(within(xgc).getByRole("button"));
    const secondDirection = order();
    expect(new Set(secondDirection.slice(-2))).toEqual(new Set(["Null Defender", "Midfielder"]));
    expect(secondDirection.slice(0, 2)).toEqual(firstDirection.slice(0, 2).reverse());
  });

  it("derives fallback bounds from horizons and never substitutes another vintage", async () => {
    const user = userEvent.setup();
    const duplicated = [
      ...playersWithActuals,
      ...playersWithActuals.map((p, index) => ({
        ...p,
        run_id: "run-b",
        // An empty fixture list must not contaminate the whole run with a synthetic GW0.
        fixtures:
          index === 0
            ? []
            : p.fixtures.map((fixture) => ({ ...fixture, gw: fixture.gw + 1 })),
      })),
    ];
    const runBHorizons = horizonsData.players.map((player) => ({
      ...player,
      run_id: "run-b",
      horizons: player.horizons.slice(0, 3).map((horizon, index) => ({
        ...horizon,
        gw_to: index + 2,
        ...(player.code === 1 && index === 2 ? { p_ge_6: 0.93 } : {}),
      })),
    }));
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players: duplicated, manifest: null });
    vi.mocked(loadPlayerHorizons).mockResolvedValueOnce({
      ...horizonsData,
      players: [
        ...horizonsData.players,
        ...runBHorizons,
      ],
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getAllByText("Alpha").length).toBe(1);
    expect(screen.getAllByText("Beta").length).toBe(1);
    // the vintage selector appears and names the default architecture
    const vintage = screen.getByRole("combobox", { name: "Forecast vintage" });
    await user.click(vintage);
    await user.click(screen.getByRole("option", { name: /run-b/ }));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "From gameweek" })).toHaveTextContent("GW2"),
    );
    expect(screen.getByRole("combobox", { name: "To gameweek" })).toHaveTextContent("GW4");
    const alpha = screen.getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("17.0")).toBeInTheDocument();
  });

  it("selects the exact cumulative xP endpoint while leaving probability detail to Player analytics", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    const alpha = () => screen.getByText("Alpha").closest("tr")!;
    expect(within(alpha()).getByText("27.0")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "To gameweek" }));
    await user.click(screen.getByRole("option", { name: "GW1" }));
    expect(screen.queryByRole("columnheader", { name: "xP GW1-1" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^xP GW1$/ })).toBeInTheDocument();
    expect(within(alpha()).getByText("7.4")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "P(≥6)" })).not.toBeInTheDocument();
  });

  it("changes current-season actuals independently from forecast GWs and resets both", async () => {
    const user = userEvent.setup();
    const players = playersWithActuals.map((player, index) => ({
      ...player,
      actuals:
        index === 0
          ? [
              actualFromForm({ goals_scored: 1 }, { gw: 1, fixture: 971 }),
              actualFromForm({ goals_scored: 2 }, { gw: 2, fixture: 972 }),
            ]
          : [actualFromForm({}, { gw: 1, fixture: 973, minutes: 0, starts: 0 })],
    }));
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: players.map((player) => ({
        season: player.season,
        code: player.code,
        actuals: player.actuals,
      })),
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("2026-27 · GW1-GW2")).toBeInTheDocument());

    const forecastFrom = screen.getByRole("combobox", { name: "From gameweek" });
    const forecastTo = screen.getByRole("combobox", { name: "To gameweek" });
    const alpha = () => screen.getByText("Alpha").closest("tr")!;
    expect(within(alpha()).getByTitle("Observed G: 3")).toHaveTextContent("3");

    await user.click(screen.getByRole("combobox", { name: "Actual from gameweek" }));
    await user.click(screen.getByRole("option", { name: "GW2" }));
    expect(screen.getByText("2026-27 · GW2")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "App" })).toHaveAttribute(
      "title",
      "Finalized 2026-27 actuals, GW2-GW2",
    );
    expect(within(alpha()).getByTitle("Observed G: 2")).toHaveTextContent("2");
    expect(forecastFrom).toHaveTextContent("GW1");
    expect(forecastTo).toHaveTextContent("GW5");

    await user.click(forecastTo);
    await user.click(screen.getByRole("option", { name: "GW1" }));
    expect(screen.getByRole("combobox", { name: "Actual from gameweek" })).toHaveTextContent("GW2");

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByRole("combobox", { name: "Actual from gameweek" })).toHaveTextContent("GW1");
    expect(screen.getByRole("combobox", { name: "Actual to gameweek" })).toHaveTextContent("GW2");
    expect(forecastTo).toHaveTextContent("GW5");
  });

  it("does not substitute a prior season until the user selects it", async () => {
    const user = userEvent.setup();
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: [
        {
          season: "2025-26",
          code: playersWithActuals[0].code,
          actuals: [actualFromForm({ goals_scored: 4 }, { gw: 38, fixture: 990 })],
        },
        {
          season: "2024-25",
          code: playersWithActuals[0].code,
          actuals: [actualFromForm({ goals_scored: 9 }, { gw: 38, fixture: 991 })],
        },
      ],
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(
      screen.getByText(/No finalized player actuals are published for 2026-27/),
    ).toHaveTextContent("another season is not substituted");
    expect(screen.queryByText("Actual GWs")).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "App" })).toHaveAttribute(
      "title",
      "No finalized 2026-27 actuals published",
    );
    expect(screen.getByText("2026-27 · no finalized GWs")).toBeInTheDocument();
    expect(within(screen.getByText("Alpha").closest("tr")!).getByTitle("No observed form is available for G"))
      .toHaveTextContent("–");

    await user.click(screen.getByRole("combobox", { name: "Actual season" }));
    expect(screen.queryByRole("option", { name: "2024-25" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "2025-26" }));
    expect(await screen.findByText("2025-26 · GW38")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "App" })).toHaveAttribute(
      "title",
      "Finalized 2025-26 actuals, GW38-GW38",
    );
    expect(within(screen.getByText("Alpha").closest("tr")!).getByTitle("Observed G: 4"))
      .toHaveTextContent("4");
  });

  it("expands a row over the shared rolling five GWs across seasons with DGWs and gaps intact", async () => {
    const user = userEvent.setup();
    const alpha = playersWithActuals[0];
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: [
        ...actualsData.players.map((player) =>
          player.code === alpha.code
            ? {
                ...player,
                actuals: [
                  actualFromForm(
                    {},
                    {
                      gw: 1,
                      fixture: 1010,
                      kickoff_time: "2026-08-15T12:00:00+00:00",
                      expected_goals: 0.25,
                      expected_assists: 0.15,
                    },
                  ),
                  actualFromForm(
                    {},
                    {
                      gw: 1,
                      fixture: 1011,
                      kickoff_time: "2026-08-15T16:00:00+00:00",
                      expected_goals: 0.4,
                      expected_assists: 0.2,
                    },
                  ),
                ],
              }
            : { ...player, actuals: [] },
        ),
        {
          season: "2025-26",
          code: alpha.code,
          actuals: [
            actualFromForm({}, { gw: 34, fixture: 1034 }),
            actualFromForm(
              {},
              {
                gw: 35,
                fixture: 1035,
                expected_goals: 0,
                expected_assists: 0,
              },
            ),
            actualFromForm(
              {},
              {
                gw: 36,
                fixture: 1036,
                minutes: 0,
                starts: 0,
                goals_scored: 0,
                assists: 0,
                expected_goals: null,
                expected_assists: 0,
                bps: null,
              },
            ),
            actualFromForm({}, { gw: 38, fixture: 1038 }),
          ],
        },
        {
          season: "2025-26",
          code: playersWithActuals[1].code,
          actuals: [actualFromForm({}, { gw: 37, fixture: 2037 })],
        },
      ],
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const alphaRow = screen.getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    await user.click(within(alphaRow!).getByRole("button", { name: /expand fixtures/i }));

    const detailHeading = await screen.findByText(/Alpha.*rolling latest five completed GWs/);
    const detailTable = detailHeading.parentElement?.querySelector("table");
    expect(detailTable).not.toBeNull();
    const detail = within(detailTable!);
    expect(detail.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Season / GW",
      "Kickoff (UTC)",
      "Min",
      "Start",
      "G",
      "A",
      "xG",
      "xA",
      "xGI",
      "CS",
      "GC",
      "Saves",
      "DC",
      "xGC",
      "Bonus",
      "BPS",
      "Pts (26/27)",
    ]);
    expect(detail.queryByRole("columnheader", { name: "xP" })).not.toBeInTheDocument();
    expect(detail.queryByText("Club λ for")).not.toBeInTheDocument();

    const fixtureRows = detail.getAllByRole("row").slice(1);
    expect(fixtureRows).toHaveLength(5);
    expect(fixtureRows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "2026-27 GW1",
      "2026-27 GW1",
      "2025-26 GW38",
      "2025-26 GW36",
      "2025-26 GW35",
    ]);
    expect(within(fixtureRows[0]).getAllByRole("cell")[1]).toHaveTextContent("2026-08-15 16:00");
    expect(within(fixtureRows[1]).getAllByRole("cell")[1]).toHaveTextContent("2026-08-15 12:00");
    expect(within(fixtureRows[3]).getAllByRole("cell")[2]).toHaveTextContent("0");
    expect(within(fixtureRows[3]).getAllByRole("cell")[8]).toHaveTextContent("–");
    expect(within(fixtureRows[3]).getAllByRole("cell")[15]).toHaveTextContent("–");
    expect(within(fixtureRows[4]).getAllByRole("cell")[8]).toHaveTextContent("0.00");
    expect(detail.queryByText("2025-26 GW34")).not.toBeInTheDocument();
  });

  it("does not fall back to forecast fixtures when selected actual history is empty", async () => {
    const user = userEvent.setup();
    const alpha = playersWithActuals[0];
    vi.mocked(loadPlayerActuals).mockResolvedValueOnce({
      ...actualsData,
      players: actualsData.players.map((player) =>
        player.code === alpha.code ? { ...player, actuals: [] } : player,
      ),
    });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const alphaRow = screen.getByText("Alpha").closest("tr");
    await user.click(within(alphaRow!).getByRole("button", { name: /expand fixtures/i }));
    expect(
      await screen.findByText("No finalized fixture history exists in the rolling latest-five-GW window."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Club λ for")).not.toBeInTheDocument();
  });

  it("sorts through a keyboard-focusable button that carries aria-sort", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /^Price/ });
    expect(header).toHaveAttribute("aria-sort", "none");
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("sorts by the selected Forecast From GW xP by default", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const gwXp = screen.getByRole("columnheader", { name: /^xP GW1$/ });
    const rangeXp = screen.getByRole("columnheader", { name: /xP GW1-5/ });
    expect(gwXp).toHaveAttribute("aria-sort", "descending");
    expect(rangeXp).toHaveAttribute("aria-sort", "none");
    await user.click(within(gwXp).getByRole("button"));
    expect(gwXp).toHaveAttribute("aria-sort", "ascending");
  });

  it("strictly sums and sorts published first-GW xP, keeping missing values last", async () => {
    const user = userEvent.setup();
    const source = playersWithActuals[0];
    const sourceFixture = source.fixtures[0];
    const player = (
      code: number,
      webName: string,
      fixtures: PlayerRecord["fixtures"],
    ): PlayerRecord => ({ ...source, code, web_name: webName, fixtures });
    const players = [
      player(21, "High xP", [{ ...sourceFixture, fixture: 921, expected_points: 7 }]),
      player(22, "Double xP", [
        { ...sourceFixture, fixture: 922, expected_points: 2.25 },
        { ...sourceFixture, fixture: 923, expected_points: 3.5 },
      ]),
      player(23, "Blank xP", [
        { ...sourceFixture, gw: 2, fixture: 924, expected_points: 4 },
      ]),
      player(24, "Missing xP", [
        { ...sourceFixture, fixture: 925, expected_points: null },
      ]),
    ];
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    vi.mocked(loadPlayerHorizons).mockResolvedValueOnce({ ...horizonsData, players: [] });

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("High xP")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /^xP GW1$/ });
    const table = header.closest("table")!;
    const order = () =>
      [...table.querySelectorAll("tbody > tr")]
        .map((row) =>
          ["High xP", "Double xP", "Blank xP", "Missing xP"].find((name) =>
            row.textContent?.includes(name),
          ),
        )
        .filter((name): name is string => name != null);

    expect(order()).toEqual(["High xP", "Double xP", "Blank xP", "Missing xP"]);
    expect(
      within(screen.getByText("Double xP").closest("tr")!).getByTitle(
        "Published xP for GW1: 5.8",
      ),
    ).toHaveTextContent("5.8");
    expect(
      within(screen.getByText("Blank xP").closest("tr")!).getByTitle(
        "Published xP for GW1: 0.0",
      ),
    ).toHaveTextContent("0.0");
    expect(
      within(screen.getByText("Missing xP").closest("tr")!).getByTitle(
        "Published xP for GW1 is unavailable",
      ),
    ).toHaveTextContent("–");

    await user.click(within(header).getByRole("button"));
    expect(order()).toEqual(["Blank xP", "Double xP", "High xP", "Missing xP"]);
  });

  it("updates the next-GW xP column from Forecast From without changing actual scope", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("2026-27 · GW1")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^xP GW1$/ })).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "From gameweek" }));
    await user.click(screen.getByRole("option", { name: "GW2" }));

    expect(screen.getByRole("columnheader", { name: /^xP GW2$/ })).toBeInTheDocument();
    expect(screen.getByText("2026-27 · GW1")).toBeInTheDocument();
    expect(
      within(screen.getByText("Alpha").closest("tr")!).getByTitle(
        "Published xP for GW2: 5.1",
      ),
    ).toHaveTextContent("5.1");
  });

  it("resets an xGI sort when the derived attack column disappears", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const xgi = screen.getByRole("columnheader", { name: "xGI" });
    const gwXp = screen.getByRole("columnheader", { name: /^xP GW1$/ });
    await user.click(within(xgi).getByRole("button"));
    expect(xgi).not.toHaveAttribute("aria-sort", "none");
    expect(gwXp).toHaveAttribute("aria-sort", "none");

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    await waitFor(() => expect(gwXp).toHaveAttribute("aria-sort", "descending"));
    expect(screen.queryByRole("columnheader", { name: "xGI" })).not.toBeInTheDocument();
  });

  it("says so when no players match the current filters", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    await user.type(screen.getByRole("spinbutton", { name: "Minimum price in millions" }), "99");
    expect(await screen.findByText("No players match the current filters.")).toBeInTheDocument();
  });

  it("clears both fixture and player filters back to the Players defaults", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    const view = screen.getByRole("radiogroup", { name: "View" });
    const venue = screen.getByRole("radiogroup", { name: "Venue filter" });
    const availability = screen.getByRole("radiogroup", { name: "Availability filter" });
    const minPrice = screen.getByRole("spinbutton", { name: "Minimum price in millions" });

    await user.click(within(view).getByRole("radio", { name: "Defense" }));
    await user.click(within(venue).getByRole("radio", { name: "Away" }));
    expect(screen.queryByRole("columnheader", { name: "P(≥6)" })).not.toBeInTheDocument();
    expect(screen.getByText(/dense Players table omits the six overlapping/i)).toBeInTheDocument();
    await user.click(within(availability).getByRole("radio", { name: "Flagged" }));
    await user.type(minPrice, "99");
    expect(await screen.findByText("No players match the current filters.")).toBeInTheDocument();

    const clear = screen.getByRole("button", { name: "Clear filters" });
    await user.click(clear);

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(within(view).getByRole("radio", { name: "Overall" })).toBeChecked();
    expect(within(venue).getByRole("radio", { name: "All" })).toBeChecked();
    expect(screen.queryByRole("columnheader", { name: "P(≥6)" })).not.toBeInTheDocument();
    expect(within(availability).getByRole("radio", { name: "All" })).toBeChecked();
    expect(minPrice).toHaveValue(null);
    expect(clear).toHaveFocus();
  });

  it("explains when the export carries no players at all", async () => {
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players: [], manifest: null });
    render(<PlayersPage />);
    expect(await screen.findByText(/No recorded forecast vintages/)).toBeInTheDocument();
  });
});
