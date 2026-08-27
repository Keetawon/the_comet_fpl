// Page smoke: the Players pivot renders from a read model without crashing -- one row
// per player of the SELECTED vintage (never one per recorded run), player filters, the
// availability overlay label, per-GW chip columns with blank slots, and the expandable
// per-fixture primitives ordered by kickoff.

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
  fetchManagerTeam,
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
  return { ...actual, fetchManagerTeam: vi.fn() };
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
  json_schema_version: 7,
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
  vi.mocked(fetchManagerTeam).mockReset();
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
    expect(
      screen.getByRole("button", { name: "Enter Players table fullscreen" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Actual 2026-27 GW1-1 App")).toBeInTheDocument();
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
    expect(screen.getByText(/7\.4/)).toBeInTheDocument();
  });

  it("filters to an exact manager squad by stable code and composes with player filters", async () => {
    const user = userEvent.setup();
    const { squad, outsider } = managerFilterPlayers();
    vi.mocked(loadPlayers).mockResolvedValueOnce({
      players: [...squad, outsider],
      manifest: null,
    });
    vi.mocked(fetchManagerTeam).mockResolvedValue(managerPreview(squad));

    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Outside Defender")).toBeInTheDocument());
    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Show my squad" }));

    expect(fetchManagerTeam).toHaveBeenCalledWith("123456", "");
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
    vi.mocked(fetchManagerTeam)
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
    vi.mocked(fetchManagerTeam).mockResolvedValueOnce(managerPreview(squad));

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
    vi.mocked(fetchManagerTeam).mockResolvedValueOnce(managerPreview(squad));

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
    vi.mocked(fetchManagerTeam).mockReturnValueOnce(
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
    vi.mocked(fetchManagerTeam).mockResolvedValueOnce(incomplete);

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
    expect(fetchManagerTeam).not.toHaveBeenCalled();
  });

  it("switches the Players-only observed columns between Overall, Attack, and Defense", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    // Overall is genuinely balanced: common, attack, and defense form are all present.
    for (const name of ["Starts", "G", "xG/90", "CS", "GC", "Saves", "DC", "xGC", "BPS"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    expect(screen.queryByRole("columnheader", { name: "G" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xG/90" })).not.toBeInTheDocument();
    for (const name of ["CS", "GC", "Saves", "DC", "xGC", "Bonus", "BPS", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("radio", { name: "Attack" }));
    expect(screen.queryByRole("columnheader", { name: "CS" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xGC" })).not.toBeInTheDocument();
    for (const name of ["G", "A", "xG", "xA", "xG/90", "xA/90", "Bonus", "BPS", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
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
    await waitFor(() => expect(screen.getByText("Actual 2026-27 GW1-2 App")).toBeInTheDocument());

    const forecastFrom = screen.getByRole("combobox", { name: "From gameweek" });
    const forecastTo = screen.getByRole("combobox", { name: "To gameweek" });
    const alpha = () => screen.getByText("Alpha").closest("tr")!;
    expect(within(alpha()).getByTitle("Observed G: 3")).toHaveTextContent("3");

    await user.click(screen.getByRole("combobox", { name: "Actual from gameweek" }));
    await user.click(screen.getByRole("option", { name: "GW2" }));
    expect(screen.getByText("Actual 2026-27 GW2-2 App")).toBeInTheDocument();
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
    expect(screen.getByText("Actual 2026-27 App")).toBeInTheDocument();
    expect(within(screen.getByText("Alpha").closest("tr")!).getByTitle("No observed form is available for G"))
      .toHaveTextContent("–");

    await user.click(screen.getByRole("combobox", { name: "Actual season" }));
    expect(screen.queryByRole("option", { name: "2024-25" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "2025-26" }));
    expect(await screen.findByText("Actual 2025-26 GW38-38 App")).toBeInTheDocument();
    expect(within(screen.getByText("Alpha").closest("tr")!).getByTitle("Observed G: 4"))
      .toHaveTextContent("4");
  });

  it("expands a row to the per-fixture primitives behind the colour", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: /expand fixtures/i })[0]);
    expect(await screen.findByText("Club λ for")).toBeInTheDocument();
    expect(screen.getByText("Club λ against")).toBeInTheDocument();
    const clubCs = screen.getByText("Club CS");
    const detailTable = clubCs.closest("table")!;
    expect(within(detailTable).getByRole("columnheader", { name: "xG" })).not.toHaveClass(
      "opacity-50",
    );
    expect(within(detailTable).getByRole("columnheader", { name: "Club CS" })).not.toHaveClass(
      "opacity-50",
    );
    expect(screen.queryByText(/form anchored 2025-26 GW38/)).not.toBeInTheDocument();
    // the detail table leads with match time, not the main table's sort
    expect(screen.getByText("Kickoff (UTC)")).toBeInTheDocument();
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

  it("sorts by the range xP column (the default sort)", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /xP GW1-5/ });
    // the page opens sorted by xP descending; clicking flips it to ascending
    expect(header).toHaveAttribute("aria-sort", "descending");
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
  });

  it("resets a sort whose form column disappears when the view changes", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const goals = screen.getByRole("columnheader", { name: "G" });
    const rangeXp = screen.getByRole("columnheader", { name: /xP GW1-5/ });
    await user.click(within(goals).getByRole("button"));
    expect(goals).not.toHaveAttribute("aria-sort", "none");
    expect(rangeXp).toHaveAttribute("aria-sort", "none");

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    await waitFor(() => expect(rangeXp).toHaveAttribute("aria-sort", "descending"));
    expect(screen.queryByRole("columnheader", { name: "G" })).not.toBeInTheDocument();
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
