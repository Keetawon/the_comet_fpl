// Page smoke: Summary and Next GW render from read models. Product ownership is explicit:
// Next GW shows only the platform default and diagnostic, while a user-custom plan remains
// in Plan Builder (and gets its own clearly labelled Summary card).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadPlayerActuals,
  loadPlayerProvisionalActuals,
  loadPlayers,
  loadSummary,
} from "@/data/load";
import summarySample from "@/data/sampleSummary.json";
import nextGwSample from "@/data/sampleNextGw.json";
import playersSample from "@/data/samplePlayers.json";
import teamsSample from "@/data/sampleFixtureMatrix.json";
import actualsSample from "@/data/samplePlayerActuals.json";
import type { NextGwPlan, PlayerActualFixture, PlayerRecord, SummaryData, TeamRecord } from "@/data/types";
import { NextGwPage } from "./NextGwPage";
import { SummaryPage } from "./SummaryPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];
const customPlan: NextGwPlan = {
  ...plans[0],
  optimizer_run_id: "custom-locked-plan",
  decision_sha256: "custom-decision",
  plan_kind: "user_custom",
  display_label: "Your plan — 1 lock, 1 exclusion",
  policy: {
    locked_codes: [1],
    excluded_codes: [2],
    min_bench_appearance: 0.25,
  },
};

function completeFiveWeekPlan(): NextGwPlan {
  const benchPerPlayer = [1, 2, 3, 4, 2];
  const positionFor = (code: number) => {
    if (code === 1 || code === 12) return "GK";
    if (code <= 5 || code === 13) return "DEF";
    if (code <= 9 || code === 14) return "MID";
    return "FWD";
  };
  const weeks = Array.from({ length: 5 }, (_, index) => {
    const gw = index + 1;
    return {
      gw,
      hit_points: 0,
      squad_cost: 1000,
      captain_code: 1,
      vice_captain_code: 2,
      players: Array.from({ length: 15 }, (_, playerIndex) => {
        const code = playerIndex + 1;
        const isStarter = code <= 11;
        return {
          code,
          web_name: `Player ${code}`,
          position: positionFor(code),
          team_code: 100 + code,
          team_short_name: `T${code}`,
          now_cost: 50,
          role: isStarter
            ? "starting_xi"
            : code === 12
              ? "bench_goalkeeper"
              : "bench_outfield",
          bench_order_index: code >= 13 ? code - 12 : null,
          is_captain: code === 1,
          is_vice_captain: code === 2,
          transferred_in: false,
          transferred_out: false,
          expected_points: isStarter ? 2 : benchPerPlayer[index],
        };
      }),
    };
  });
  const player_xp = Object.fromEntries(
    Array.from({ length: 15 }, (_, playerIndex) => {
      const code = playerIndex + 1;
      return [
        String(code),
        Object.fromEntries(
          weeks.map((week, index) => [
            String(week.gw),
            code <= 11 ? 2 : benchPerPlayer[index],
          ]),
        ),
      ];
    }),
  );
  return { ...plans[0], weeks, player_xp } as NextGwPlan;
}

vi.mock("@/data/load", () => ({
  loadSummary: vi.fn(),
  loadNextGw: vi.fn(),
  loadPlayerActuals: vi.fn(),
  loadPlayerProvisionalActuals: vi.fn(),
  loadPlayers: vi.fn(),
  loadFixtureMatrix: vi.fn(),
}));

const teamsForRunA: TeamRecord[] = teamsSample.teams.map((t) => ({ ...t, run_id: "run-a" }));

beforeAll(() => {
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-20T12:00:00Z"));
  window.localStorage.clear();
  vi.mocked(loadSummary).mockResolvedValue(summarySample as unknown as SummaryData);
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadPlayerActuals).mockResolvedValue({ schema: "fpl.dashboard-player-actuals", json_schema_version: 9, players: [] });
  vi.mocked(loadPlayerProvisionalActuals).mockResolvedValue({ schema: "fpl.dashboard-player-provisional-actuals", json_schema_version: 1, captured_at: null, players: [] });
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersSample.players, manifest: null });
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: teamsForRunA,
    schedule: {
      schema_version: 1,
      semantics: "current_at_export_not_forecast_vintage",
      export_created_at: "2026-08-20T00:00:00+00:00",
      database_sha256: "d".repeat(64),
      teams: teamsForRunA,
    },
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
});
afterEach(() => vi.restoreAllMocks());

it("does not present the previous GW plan as the next GW suggestion", async () => {
  vi.mocked(Date.now).mockReturnValue(Date.parse("2026-08-29T12:00:00Z"));
  const before = JSON.stringify(plans);
  render(<NextGwPage />);
  expect(await screen.findByText(/No platform optimizer plan is published for 2026-27 GW2/)).toBeVisible();
  expect(screen.queryByRole("columnheader", { name: "Plan xP GW1" })).not.toBeInTheDocument();
  expect(JSON.stringify(plans)).toBe(before);
});

it("selects the available next-GW plan instead of an older default", async () => {
  vi.mocked(Date.now).mockReturnValue(Date.parse("2026-08-29T12:00:00Z"));
  const next = structuredClone(plans[0]);
  next.optimizer_run_id = "next-gw-plan";
  next.gw_from += 1; next.gw_to += 1;
  next.weeks = next.weeks.map((week) => ({ ...week, gw: week.gw + 1 }));
  vi.mocked(loadNextGw).mockResolvedValue({ plans: [...plans, next] });
  render(<NextGwPage />);
  expect(await screen.findByRole("columnheader", { name: "Plan xP GW2" })).toBeVisible();
  expect(screen.queryByRole("columnheader", { name: "Plan xP GW1" })).not.toBeInTheDocument();
});

it.each([true, false, undefined])("shows the defender rule only when the selected platform plan used it: %s", async (enabled) => {
  const platform = structuredClone(plans[0]);
  platform.policy.single_defender_per_club = enabled;
  vi.mocked(loadNextGw).mockResolvedValue({ plans: [customPlan, platform] });
  render(<NextGwPage />);
  await screen.findByRole("columnheader", { name: "Plan xP GW1" });
  expect(screen.queryByText("One DEF per club (Arsenal exempt)") !== null).toBe(enabled === true);
});

describe("SummaryPage", () => {
  it("shows next GW, optimizer squad summaries, availability watch, and watchlists", async () => {
    render(<SummaryPage />);
    await waitFor(() => expect(screen.getByText(/2026-27 · GW1-3/)).toBeInTheDocument());
    expect(screen.getByText(/First kickoff 2026-08-22 14:00 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Deadlines are not sourced/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    // one platform card per formal plan, labelled by product role, never comparing EV
    expect(screen.getByText("Platform recommendation — default")).toBeInTheDocument();
    expect(screen.getByText("Platform diagnostic sensitivity")).toBeInTheDocument();
    expect(screen.getAllByText(/GW1 squad xP/).length).toBe(2); // one card per plan
    // Legacy forecast status must not masquerade as current FPL reporting.
    expect(screen.getByText(/Availability watch/)).toBeInTheDocument();
    expect(screen.getByText(/Current availability is unknown/)).toBeInTheDocument();
    expect(screen.queryByText(/doubtful 75%/)).not.toBeInTheDocument();
    // player and team watchlists derive from the selected vintage
    expect(screen.getByRole("heading", { name: "Top 15 players · GW1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "A kinder run of fixtures" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "A tougher run ahead" })).toBeInTheDocument();
  });

  it("separates a saved custom plan from the formal platform cards", async () => {
    window.localStorage.setItem("fpl-solved-plan", customPlan.optimizer_run_id);
    vi.mocked(loadNextGw).mockResolvedValue({ plans: [customPlan, plans[1], plans[0]] });

    render(<SummaryPage />);

    expect(await screen.findByText("Your custom plan")).toBeInTheDocument();
    expect(screen.getByText(/1 locked · 1 excluded · bench floor 25%/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open your plan in Plan Builder/ })).toHaveAttribute(
      "href",
      "#plan-builder?run=custom-locked-plan",
    );
    expect(screen.getByText("Platform recommendation — default")).toBeInTheDocument();
    expect(screen.getByText("Platform diagnostic sensitivity")).toBeInTheDocument();
  });

  it("still renders when browser storage rejects the saved custom-plan lookup", async () => {
    vi.mocked(loadNextGw).mockResolvedValue({ plans: [customPlan, plans[1], plans[0]] });
    const storage = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("storage denied", "SecurityError");
    });
    try {
      render(<SummaryPage />);
      expect(await screen.findByText("Your custom plan")).toBeInTheDocument();
      expect(screen.getByText("Platform recommendation — default")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Open your plan in Plan Builder/ })).toHaveAttribute(
        "href",
        "#plan-builder?run=custom-locked-plan",
      );
    } finally {
      storage.mockRestore();
    }
  });
});

describe("NextGwPage", () => {
  it("renders the default plan's XI, captain, bench, the squad pivot, and the diff card", async () => {
    render(<NextGwPage />);
    await waitFor(() =>
      expect(screen.getByText(/Platform Next GW suggestion — GW1/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Formation/).textContent).toContain("captain Alpha");
    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Enter Next GW suggestion players table fullscreen",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Formation/).textContent).toContain("vice Beta");
    expect(screen.getByText(/Bench \(autosub order/)).toBeInTheDocument();
    // the squad table is the shared pivot: plan EV columns beside the GW fixture chips
    expect(screen.getByRole("columnheader", { name: /Plan xP GW1/ })).toBeInTheDocument();
    // Players-page view switching must not widen this decision table's legacy form profile.
    expect(screen.getByRole("columnheader", { name: "G" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Starts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "CS" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "DC" })).not.toBeInTheDocument();
    for (const name of ["Saves/App", "DC/App", "xGC/App", "Pts/App"]) {
      expect(screen.queryByRole("columnheader", { name })).not.toBeInTheDocument();
    }
    expect(screen.getAllByTestId("chip").length).toBeGreaterThan(0);
    // This shared table intentionally keeps its prospective fixture expansion.
    const tableShell = screen
      .getByRole("button", { name: "Enter Next GW suggestion players table fullscreen" })
      .closest<HTMLElement>("[data-fullscreen-mode]");
    expect(tableShell).not.toBeNull();
    await userEvent.click(
      within(tableShell!).getAllByRole("button", { name: /expand fixtures/i })[0],
    );
    expect(within(tableShell!).getByText("Club λ for")).toBeInTheDocument();
    expect(within(tableShell!).getByRole("columnheader", { name: "xP" })).toBeInTheDocument();
    // captain badge marks Alpha in the table
    expect(screen.getAllByText("C").length).toBeGreaterThan(0);
    // the diff card reports overlap and never compares EV across architectures
    expect(screen.getByText(/Default vs diagnostic \(GW1\)/)).toBeInTheDocument();
    expect(screen.getByText(/squad overlap 2\/3/)).toBeInTheDocument();
    expect(screen.getByText(/captain differs/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Forward team to Squad Draft" }),
    ).toHaveAttribute("href", "#squad-draft?optimizer_run_id=opt-default");
  });

  it("widens the EV horizon via the bounded selector", async () => {
    const user = userEvent.setup();
    render(<NextGwPage />);
    await waitFor(() =>
      expect(screen.getByText(/Platform Next GW suggestion — GW1/)).toBeInTheDocument(),
    );
    await user.click(screen.getByText("3 GWs"));
    expect(await screen.findByText("19.0")).toBeInTheDocument(); // 7.4 + 6.1 + 5.5
  });

  it("switches the pivot to compare the whole roster", async () => {
    const user = userEvent.setup();
    render(<NextGwPage />);
    await waitFor(() =>
      expect(screen.getByText(/Platform Next GW suggestion — GW1/)).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Compare all players"));
    // the whole run-a roster (Alpha, Beta) renders -- Gamma has no read-model row
    expect(await screen.findByText("Squad only")).toBeInTheDocument();
    expect(screen.getAllByText("Alpha").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Beta").length).toBeGreaterThan(0);
  });

  it("colour-codes suggestion rows by role: captain gold, vice pale gold, bench grey", async () => {
    render(<NextGwPage />);
    await waitFor(() =>
      expect(screen.getByText(/Platform Next GW suggestion — GW1/)).toBeInTheDocument(),
    );
    const rowsOf = (name: string) =>
      screen.getAllByText(name).flatMap((element) => {
        const row = element.closest("tr");
        return row ? [row] : [];
      });
    // Alpha captains the default plan: a gold-highlighted row with an amber accent.
    expect(rowsOf("Alpha").some((row) => row.className.includes("bg-amber-100"))).toBe(true);
    // Beta is the vice-captain starter: the paler amber variant.
    expect(rowsOf("Beta").some((row) => row.className.includes("bg-amber-50"))).toBe(true);
    expect(screen.getByText(/row colours: gold = captain/)).toBeInTheDocument();
  });

  it("ignores a saved custom V3 plan and keeps the formal selector unique and platform-only", async () => {
    // Reproduce the screenshot bug exactly: a custom V3 plan sorts before the formal V3 plan,
    // shares its architecture, and is also the locally saved solved run.
    window.localStorage.setItem("fpl-solved-plan", customPlan.optimizer_run_id);
    vi.mocked(loadNextGw).mockResolvedValue({ plans: [customPlan, plans[1], plans[0]] });

    render(<NextGwPage />);
    await waitFor(() =>
      expect(screen.getByText(/Platform Next GW suggestion — GW1/)).toBeInTheDocument(),
    );

    expect(screen.getByText(/Formal platform recommendation/)).toBeInTheDocument();
    expect(screen.getByText(/Optimizer run opt-default/)).toBeInTheDocument();
    expect(screen.queryByText(/custom-locked/)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Platform model" })).toHaveTextContent(
      plans[0].display_label,
    );
    expect(screen.queryByText(customPlan.display_label)).not.toBeInTheDocument();
  });

  it("shows full post-transfer plan xP sums as player-table footer rows", async () => {
    const user = userEvent.setup();
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [completeFiveWeekPlan(), plans[1]],
    });

    render(<NextGwPage />);
    await screen.findByText(/Platform Next GW suggestion/);

    expect(
      screen.queryByRole("region", { name: "Squad xP and Bench Boost outlook" }),
    ).not.toBeInTheDocument();
    const footer = screen.getByRole("rowgroup", { name: "Planned squad xP totals" });
    const xiRow = within(footer).getByRole("rowheader", {
      name: "Planned XI xP (11)",
    }).closest("tr");
    const benchRow = within(footer).getByRole("rowheader", {
      name: "Planned bench xP (4)",
    }).closest("tr");
    const squadRow = within(footer).getByRole("rowheader", {
      name: "Planned squad xP (15)",
    }).closest("tr");

    expect(xiRow).toHaveTextContent("110.0");
    expect(xiRow).toHaveTextContent("22.0");
    expect(benchRow).toHaveTextContent("48.0");
    expect(benchRow).toHaveTextContent("4.0");
    expect(benchRow).toHaveTextContent("8.0");
    expect(benchRow).toHaveTextContent("12.0");
    expect(benchRow).toHaveTextContent("16.0");
    expect(squadRow).toHaveTextContent("158.0");
    expect(squadRow).toHaveTextContent("26.0");
    expect(
      within(footer).getByTitle(
        "Highest complete planned bench xP in the loaded horizon",
      ),
    ).toHaveTextContent("16.0");
    expect(within(footer).getAllByRole("row").at(-1)).toBe(squadRow);
    expect(footer).not.toHaveTextContent("Full selected post-transfer plan");
    expect(
      screen.getByText(
        /Full selected post-transfer plan; raw player xP sums, unaffected by table filters/,
      ),
    ).toHaveTextContent(
      "Highest complete bench xP in this loaded horizon: GW4.",
    );

    await user.click(screen.getByText("3 GWs"));
    expect(benchRow).toHaveTextContent("24.0");
    expect(squadRow).toHaveTextContent("90.0");

    await user.click(screen.getByText("Compare all players"));
    expect(benchRow).toHaveTextContent("48.0");
    expect(squadRow).toHaveTextContent("158.0");
  });
});

// Synthetic current-season observations, independent of the forecast's archived form.
function observedFixture(gw: number, fixture: number, patch: Partial<PlayerActualFixture> = {}): PlayerActualFixture {
  return { ...actualsSample.players[0].actuals[0], gw, fixture,
    kickoff_time: `2026-09-${String(gw + 1).padStart(2, "0")}T14:00:00+00:00`,
    points_under_rules_2026_27: 5, ...patch };
}

function showUpcomingGwSeven() {
  vi.mocked(Date.now).mockReturnValue(Date.parse("2026-10-10T12:00:00Z"));
  const plan = structuredClone(plans[0]);
  plan.gw_from = 7; plan.gw_to = 11;
  plan.weeks = plan.weeks.map((week) => ({ ...week, gw: 7 }));
  vi.mocked(loadNextGw).mockResolvedValue({ plans: [plan] });
  const teams = teamsForRunA.map((team) => ({ ...team,
    fixtures: team.fixtures.map((fixture) => ({ ...fixture, gw: 7, kickoff_time: "2026-10-17T14:00:00Z" })) }));
  vi.mocked(loadFixtureMatrix).mockResolvedValue({ teams, schedule: {
    schema_version: 1, semantics: "current_at_export_not_forecast_vintage",
    export_created_at: "2026-10-10T00:00:00Z", database_sha256: "d".repeat(64), teams,
  }, manifest: null, easeIndexFormulaVersion: "fixture-ease-v1" });
}

function observedCell(name: string, header: string) {
  const row = screen.getAllByText(name).map((element) => element.closest("tr")).find(Boolean)!;
  const head = screen.getByRole("columnheader", { name: header });
  const index = Array.from(head.parentElement!.children).indexOf(head);
  return within(row).getAllByRole("cell")[index];
}

it("fills missing form from current observed fixtures, includes DGWs, and uses one shared season window", async () => {
  showUpcomingGwSeven();
  const players: PlayerRecord[] = structuredClone(playersSample.players);
  players.find((player) => player.code === 1 && player.run_id === "run-a")!.form = null;
  const before = JSON.stringify(players);
  vi.mocked(loadPlayers).mockResolvedValue({ players, manifest: null });
  vi.mocked(loadPlayerActuals).mockResolvedValue({ schema: "fpl.dashboard-player-actuals", json_schema_version: 9, players: [
    { season: "2025-26", code: 1, actuals: [observedFixture(38, 380, { points_under_rules_2026_27: 999 })] },
    { season: "2026-27", code: 1, actuals: [
      observedFixture(1, 1, { points_under_rules_2026_27: 100 }),
      observedFixture(2, 2, { points_under_rules_2026_27: 2 }),
      observedFixture(2, 22, { minutes: 60, points_under_rules_2026_27: 3 }),
    ] },
    { season: "2026-27", code: 2, actuals: [3, 4, 5, 6].map((gw) => observedFixture(gw, gw)) },
  ] });
  render(<NextGwPage />);
  await screen.findByRole("columnheader", { name: "Plan xP GW7" });
  expect(screen.getByText(/2026-27 GW2 to 2026-27 GW6; 5 ended gameweeks/)).toBeVisible();
  expect(observedCell("Alpha", "Last 5 App")).toHaveTextContent("2");
  expect(observedCell("Alpha", "Min/g")).toHaveTextContent("75");
  expect(observedCell("Alpha", "Pts")).toHaveTextContent("5");
  expect(observedCell("Beta", "Pts")).toHaveTextContent("20");
  const user = userEvent.setup();
  await user.click(screen.getByRole("combobox", { name: "Past form window" }));
  await user.click(screen.getByRole("option", { name: "Last 3" }));
  expect(observedCell("Alpha", "Pts")).toHaveTextContent("\u2013");
  expect(observedCell("Beta", "Pts")).toHaveTextContent("15");
  expect(JSON.stringify(players)).toBe(before);
});

it("marks provisional points, prefers finalized duplicates, and leaves absent history unavailable", async () => {
  showUpcomingGwSeven();
  const finalized = observedFixture(6, 6, { points_under_rules_2026_27: 2, expected_goals: null });
  const { points_under_rules_2026_27: _points, ...sameFixture } = finalized;
  vi.mocked(loadPlayerActuals).mockResolvedValue({ schema: "fpl.dashboard-player-actuals", json_schema_version: 9, players: [
    { season: "2026-27", code: 1, actuals: [finalized] },
  ] });
  vi.mocked(loadPlayerProvisionalActuals).mockResolvedValue({ schema: "fpl.dashboard-player-provisional-actuals", json_schema_version: 1, captured_at: "2026-10-10T00:00:00Z", players: [
    { season: "2026-27", code: 1, actuals: [
      { ...sameFixture, total_points_as_recorded: 999 },
      { ...sameFixture, fixture: 61, minutes: 60, total_points_as_recorded: 4 },
      { ...sameFixture, fixture: 62, minutes: 0, total_points_as_recorded: 0 },
    ] },
  ] });
  render(<NextGwPage />);
  await screen.findByRole("columnheader", { name: "Plan xP GW7" });
  expect(observedCell("Alpha", "Last 5 App")).toHaveTextContent("2");
  expect(observedCell("Alpha", "Min/g")).toHaveTextContent("75");
  expect(observedCell("Alpha", "Pts")).toHaveTextContent("6");
  expect(within(observedCell("Alpha", "Pts")).getByLabelText("includes provisional raw FPL points")).toBeVisible();
  expect(observedCell("Alpha", "xG")).toHaveTextContent("\u2013");
  expect(observedCell("Beta", "Pts")).toHaveTextContent("\u2013");
  expect(screen.getByText(/2026-27 GW6 \(provisional\).*1 ended gameweeks/)).toBeVisible();
  const user = userEvent.setup();
  await user.type(screen.getByRole("spinbutton", { name: "Minimum average minutes over the last 5" }), "70");
  expect(observedCell("Alpha", "Min/g")).toHaveTextContent("75");
});
