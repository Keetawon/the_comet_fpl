// Page smoke: Summary and Next GW render from read models. Product ownership is explicit:
// Next GW shows only the platform default and diagnostic, while a user-custom plan remains
// in Plan Builder (and gets its own clearly labelled Summary card).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadPlayers,
  loadSummary,
} from "@/data/load";
import summarySample from "@/data/sampleSummary.json";
import nextGwSample from "@/data/sampleNextGw.json";
import playersSample from "@/data/samplePlayers.json";
import teamsSample from "@/data/sampleFixtureMatrix.json";
import type { NextGwPlan, SummaryData, TeamRecord } from "@/data/types";
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
  loadPlayers: vi.fn(),
  loadFixtureMatrix: vi.fn(),
}));

const teamsForRunA: TeamRecord[] = teamsSample.teams.map((t) => ({ ...t, run_id: "run-a" }));

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(loadSummary).mockResolvedValue(summarySample as unknown as SummaryData);
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersSample.players, manifest: null });
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
});

describe("SummaryPage", () => {
  it("shows next GW, optimizer squad summaries, availability watch, and watchlists", async () => {
    render(<SummaryPage />);
    await waitFor(() => expect(screen.getByText(/2026-27 · GW1-3/)).toBeInTheDocument());
    expect(screen.getByText(/first kickoff 2026-08-22 11:30 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Deadlines are not sourced/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    // one platform card per formal plan, labelled by product role, never comparing EV
    expect(screen.getByText("Platform recommendation — default")).toBeInTheDocument();
    expect(screen.getByText("Platform diagnostic sensitivity")).toBeInTheDocument();
    expect(screen.getAllByText(/GW1 squad xP/).length).toBe(2); // one card per plan
    // availability watch labels the official overlay status and chance
    expect(screen.getByText(/Availability watch/)).toBeInTheDocument();
    expect(screen.getByText(/doubtful 75%/)).toBeInTheDocument();
    // player and team watchlists derive from the selected vintage
    expect(screen.getAllByText(/Players to watch/).length).toBe(2);
    expect(screen.getByText(/easiest schedules/)).toBeInTheDocument();
    expect(screen.getByText(/hardest schedules/)).toBeInTheDocument();
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
