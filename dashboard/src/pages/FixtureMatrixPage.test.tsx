// Page smoke: the Fixture matrix pivot renders from a read model -- one row per club of
// the selected vintage, per-GW chip columns with blank slots, the three colour sources,
// default sort by the selected horizon measure, and opponent-strength colouring direction
// (a weak opponent colours green, a strong opponent red, regardless of the row club).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw, loadTeamActuals, loadTeamProvisionalActuals } from "@/data/load";
import sample from "@/data/sampleFixtureMatrix.json";
import nextGwSample from "@/data/sampleNextGw.json";
import type {
  FixtureScheduleOverlay,
  NextGwPlan,
  TeamActualFixture,
  TeamActualsData,
} from "@/data/types";
import { FixtureMatrixPage } from "./FixtureMatrixPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];

const actual = (patch: Partial<TeamActualFixture> = {}): TeamActualFixture => ({
  gw: 1,
  fixture: 10,
  kickoff_time: "2026-08-22T14:00:00+00:00",
  opponent_team_code: 102,
  opponent_short_name: "BET",
  was_home: true,
  goals_for: 2,
  goals_against: 1,
  team_xg: 1.75,
  team_xgc: 0.91,
  team_bps: 72,
  defensive_contribution: 61,
  ...patch,
});

const teamActuals: TeamActualsData = {
  schema: "fpl.dashboard-team-actuals",
  json_schema_version: 9,
  teams: [
    {
      season: "2025-26",
      team_code: 101,
      actuals: [
        actual({
          gw: 38,
          fixture: 380,
          kickoff_time: "2026-05-24T15:00:00+00:00",
          opponent_team_code: 199,
          opponent_short_name: "OME",
          was_home: false,
          goals_for: 4,
          goals_against: 2,
        }),
      ],
    },
    {
      season: "2026-27",
      team_code: 101,
      actuals: [
        actual({ gw: 1, fixture: 100, kickoff_time: "2026-08-15T14:00:00+00:00" }),
        actual({ gw: 2, fixture: 200, kickoff_time: "2026-08-22T14:00:00+00:00" }),
        actual({ gw: 3, fixture: 300, kickoff_time: "2026-08-29T14:00:00+00:00" }),
        actual({ gw: 4, fixture: 400, kickoff_time: "2026-09-05T14:00:00+00:00" }),
        actual({ gw: 5, fixture: 500, kickoff_time: "2026-09-12T14:00:00+00:00" }),
        actual({
          gw: 6,
          fixture: 601,
          kickoff_time: "2026-09-19T12:00:00+00:00",
          goals_for: 0,
          goals_against: 0,
          team_xg: null,
          team_xgc: null,
          team_bps: null,
          defensive_contribution: null,
        }),
        actual({
          gw: 6,
          fixture: 602,
          kickoff_time: "2026-09-19T18:00:00+00:00",
          opponent_team_code: 103,
          opponent_short_name: "GAM",
          was_home: false,
        }),
      ],
    },
    {
      season: "2026-27",
      team_code: 102,
      actuals: [
        actual({ gw: 1, fixture: 101, opponent_team_code: 101, opponent_short_name: "ALP" }),
        actual({ gw: 3, fixture: 301, opponent_team_code: 101, opponent_short_name: "ALP" }),
        actual({ gw: 6, fixture: 603, opponent_team_code: 101, opponent_short_name: "ALP" }),
      ],
    },
  ],
};
const schedule: FixtureScheduleOverlay = {
  schema_version: 2,
  semantics: "current_at_export_not_forecast_vintage",
  export_created_at: "2026-08-20T12:00:00+00:00",
  database_sha256: "d".repeat(64),
  teams: [
    {
      season: "2026-27",
      team_code: 101,
      team_name: "Alpha",
      short_name: "ALP",
      fixtures: [
        ...Array.from({ length: 11 }, (_, index) => {
          const gw = index + 5;
          return {
            gw,
            fixture: gw === 6 ? 100 : 200 + gw,
            kickoff_time: `2026-10-${String(gw).padStart(2, "0")}T14:00:00+00:00`,
            opponent_team_code: 102,
            opponent_short_name: "BET",
            was_home: gw % 2 === 1,
            official_fdr: 2,
          };
        }),
        {
          gw: 6,
          fixture: 906,
          kickoff_time: "2026-10-06T18:00:00+00:00",
          opponent_team_code: 103,
          opponent_short_name: "GAM",
          was_home: true,
          official_fdr: null,
        },
      ],
    },
    {
      season: "2026-27",
      team_code: 102,
      team_name: "Beta",
      short_name: "BET",
      fixtures: Array.from({ length: 11 }, (_, index) => {
        const gw = index + 5;
        return {
          gw,
          fixture: gw === 6 ? 100 : 200 + gw,
          kickoff_time: `2026-10-${String(gw).padStart(2, "0")}T14:00:00+00:00`,
          opponent_team_code: 101,
          opponent_short_name: "ALP",
          was_home: gw % 2 === 0,
          official_fdr: 4,
        };
      }).filter((fixture) => fixture.gw !== 7),
    },
  ],
};

vi.mock("@/data/load", () => ({
  loadFixtureMatrix: vi.fn(),
  loadNextGw: vi.fn(),
  loadTeamActuals: vi.fn(),
  loadTeamProvisionalActuals: vi.fn(),
}));

beforeEach(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: sample.teams,
    schedule,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadTeamActuals).mockResolvedValue(teamActuals);
  vi.mocked(loadTeamProvisionalActuals).mockResolvedValue({
    schema: "fpl.dashboard-team-provisional-actuals",
    json_schema_version: 1,
    captured_at: null,
    teams: [],
  });
});

describe("FixtureMatrixPage", () => {
  it("renders one row per club with per-GW chips, blank slots, and all colour sources", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    const fullscreenButton = screen.getByRole("button", {
      name: "Enter Fixture matrix table fullscreen",
    });
    expect(fullscreenButton).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Filters" }).nextElementSibling).toContainElement(
      fullscreenButton,
    );
    expect(screen.getAllByRole("button", { name: /Fixture matrix table fullscreen/ })).toHaveLength(1);
    expect(screen.getAllByText("Beta").length).toBeGreaterThan(0);
    // recent form from the anchor season, one compact line
    expect(screen.getByText(/W3 D1 L1/)).toBeInTheDocument();
    // the three colour sources and the three views are reachable
    expect(screen.getByText("Opponent strength")).toBeInTheDocument();
    expect(screen.getByText("Club ease")).toBeInTheDocument();
    expect(screen.getByText("Official FDR")).toBeInTheDocument();
    expect(screen.getByText("Attack")).toBeInTheDocument();
    // per-GW pivot cells: chips for played gameweeks, blank slots for missing ones
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByTestId("blank-slot").length).toBeGreaterThanOrEqual(1);
  });

  it("adds provisional GW2 to Rolling 5 and labels the mutable team score", async () => {
    const user = userEvent.setup();
    vi.mocked(loadTeamActuals).mockResolvedValueOnce({
      ...teamActuals,
      teams: [
        {
          season: "2026-27",
          team_code: 101,
          actuals: [actual({ gw: 1, fixture: 10, goals_for: 2, goals_against: 1 })],
        },
        {
          season: "2026-27",
          team_code: 102,
          actuals: [
            actual({
              gw: 1,
              fixture: 10,
              opponent_team_code: 101,
              opponent_short_name: "ALP",
              was_home: false,
              goals_for: 1,
              goals_against: 2,
            }),
          ],
        },
      ],
    });
    vi.mocked(loadTeamProvisionalActuals).mockResolvedValueOnce({
      schema: "fpl.dashboard-team-provisional-actuals",
      json_schema_version: 1,
      captured_at: "2026-09-01T09:00:00+07:00",
      teams: [
        {
          season: "2026-27",
          team_code: 101,
          actuals: [
            actual({
              gw: 2,
              fixture: 20,
              kickoff_time: "2026-08-29T14:00:00+00:00",
              goals_for: 3,
              goals_against: 1,
            }),
          ],
        },
        {
          season: "2026-27",
          team_code: 102,
          actuals: [
            actual({
              gw: 2,
              fixture: 20,
              kickoff_time: "2026-08-29T14:00:00+00:00",
              opponent_team_code: 101,
              opponent_short_name: "ALP",
              was_home: false,
              goals_for: 1,
              goals_against: 3,
            }),
          ],
        },
      ],
    });

    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByRole("combobox", { name: "Actual scope" })).toHaveTextContent(
      "Rolling 5",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Provisional team results are included from the live capture at 2026-09-01 02:00 UTC",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "never used on prediction-vs-actual pages",
    );

    const alphaRow = screen.getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    await user.click(
      within(alphaRow!).getByRole("button", { name: "Expand recent results" }),
    );
    const detail = screen.getByTestId("team-actual-details-101");
    expect(detail).toHaveTextContent(
      "shared window 2026-27 GW2 (provisional), 2026-27 GW1",
    );
    const provisionalRow = detail.querySelector<HTMLElement>('[data-actual-fixture="20"]');
    expect(provisionalRow).not.toBeNull();
    expect(within(provisionalRow!).getByText("Provisional")).toBeInTheDocument();
    const cells = within(provisionalRow!).getAllByRole("cell");
    expect(cells[3]).toHaveTextContent("3");
    expect(cells[4]).toHaveTextContent("1");
  });

  it("defaults to opponent-strength colouring: weak opponent green, strong opponent red", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    // Beta (model λ: scores little, concedes lots) reads ~90 -> green end
    const alphaGw1 = screen.getAllByTestId("chip").find(
      (c) => c.dataset.gw === "1" && c.closest("tr")!.textContent!.includes("Alpha"),
    )!;
    expect(alphaGw1.dataset.bucket).toBe("easier");
    expect(alphaGw1.className).toContain("bg-green");
    // Alpha (model λ: strong both ways) reads ~120 -> red end
    const betaGw1 = screen.getAllByTestId("chip").find(
      (c) => c.dataset.gw === "1" && c.closest("tr")!.textContent!.includes("Beta"),
    )!;
    expect(betaGw1.dataset.bucket).toBe("harder");
    expect(betaGw1.className).toContain("bg-red");
  });

  it("defaults the table to average opponent strength and sorts highest first", async () => {
    const { container } = render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(
      screen.getByRole("columnheader", { name: /Avg Opp str \(GW1-5\)/ }),
    ).toBeInTheDocument();
    const rows = container.querySelectorAll("tbody > tr");
    const firstTeamRow = [...rows].find(
      (r) => r.textContent?.includes("Beta") || r.textContent?.includes("Alpha"),
    );
    // Beta faces strong Alpha (~120); Alpha's measured opponents are weak Beta (~90).
    expect(firstTeamRow!.textContent).toContain("Beta");
  });

  it("switches the average, card headline, and tier bucket together for every source tab", async () => {
    const user = userEvent.setup();
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    await user.click(screen.getByRole("radio", { name: "Attack" }));
    expect(
      screen.getByRole("columnheader", { name: /Avg Opp str \(GW1-5\)/ }),
    ).toBeInTheDocument();
    const alphaAttackRow = screen.getByText("Alpha").closest("tr");
    expect(alphaAttackRow).not.toBeNull();
    const alphaAttackGw1 = within(alphaAttackRow!)
      .getAllByTestId("chip")
      .find((chip) => chip.dataset.gw === "1");
    expect(alphaAttackGw1).toHaveTextContent(/GW1 · 90/);
    expect(alphaAttackGw1).toHaveAttribute("data-bucket", "easier");
    expect(
      screen.getByText(/highest selected-view modelled published expected goals for at 2\.10/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Official FDR" }));
    expect(screen.getByRole("columnheader", { name: "Avg FDR" })).toBeInTheDocument();
    const attackWithFdr = within(alphaAttackRow!)
      .getAllByTestId("chip")
      .find((chip) => chip.dataset.gw === "1");
    expect(attackWithFdr).toHaveTextContent("FDR 2");
    expect(attackWithFdr).toHaveAttribute("data-bucket", "easier");
    expect(attackWithFdr).toHaveAccessibleName(/selected official FDR 2/i);

    await user.click(screen.getByRole("radio", { name: "10 GWs" }));
    expect(screen.getByRole("columnheader", { name: "Avg FDR" })).toBeInTheDocument();
    const scheduleOnlyAttack = within(alphaAttackRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(scheduleOnlyAttack).toHaveTextContent("GW6 · FDR 2");
    expect(scheduleOnlyAttack).toHaveAttribute("data-bucket", "easier");
    expect(scheduleOnlyAttack).toHaveAccessibleName(/selected metric is current official FDR 2/i);

    await user.click(screen.getByRole("radio", { name: "Club ease" }));
    await user.click(screen.getByRole("radio", { name: "Defense" }));
    expect(
      screen.getByRole("columnheader", { name: /Avg Club ease \(GW1-10\)/ }),
    ).toBeInTheDocument();
    const alphaDefenseRow = screen.getByText("Alpha").closest("tr");
    expect(alphaDefenseRow).not.toBeNull();
    const alphaDefenseGw1 = within(alphaDefenseRow!)
      .getAllByTestId("chip")
      .find((chip) => chip.dataset.gw === "1");
    expect(alphaDefenseGw1).toHaveTextContent(/GW1 · 131/);
    expect(alphaDefenseGw1).toHaveAttribute("data-bucket", "much-easier");
    expect(alphaDefenseGw1).toHaveAccessibleName(/selected club defense ease index 131/i);
  });

  it("colours later fixtures with explicit proxies and current official FDR", async () => {
    const user = userEvent.setup();
    const { container } = render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    expect(screen.getByRole("columnheader", { name: "GW5" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "GW6" })).not.toBeInTheDocument();
    const firstTeamBefore = [...container.querySelectorAll("tbody > tr")].find(
      (row) => row.textContent?.includes("Beta") || row.textContent?.includes("Alpha"),
    )?.textContent;
    expect(
      screen.getByRole("columnheader", { name: /Avg Opp str \(GW1-5\)/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "10 GWs" }));
    expect(screen.getByRole("columnheader", { name: "GW10" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "GW11" })).not.toBeInTheDocument();
    const alphaRow = screen.getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    const alphaGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(alphaGw6).toBeDefined();
    expect(alphaGw6).toHaveAttribute("data-bucket", "easier");
    expect(alphaGw6!.className).toContain("bg-green");
    expect(alphaGw6).toHaveTextContent(/GW6 · 90/);
    expect(alphaGw6).toHaveAccessibleName(
      /selected metric is selected-vintage opponent strength proxy 90.*GW1-GW4 team lambdas/i,
    );
    const gammaGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("GAM"));
    expect(gammaGw6).toHaveAttribute("data-bucket", "null");
    expect(gammaGw6!.className).toContain("bg-muted");
    const betaRow = screen.getByText("Beta").closest("tr");
    expect(betaRow).not.toBeNull();
    const betaGw6 = within(betaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("ALP"));
    expect(betaGw6).toHaveAttribute("data-bucket", "harder");
    expect(betaGw6!.className).toContain("bg-red");
    expect(
      within(alphaRow!)
        .getAllByTestId("schedule-chip")
        .filter((chip) => chip.dataset.gw === "6"),
    ).toHaveLength(2);
    const betaAfter = screen.getByText("Beta").closest("tr");
    expect(betaAfter).not.toBeNull();
    expect(
      within(betaAfter!)
        .getAllByTestId("blank-slot")
        .some((slot) => slot.dataset.gw === "7"),
    ).toBe(true);
    const firstTeamAfter = [...container.querySelectorAll("tbody > tr")].find(
      (row) => row.textContent?.includes("Beta") || row.textContent?.includes("Alpha"),
    )?.textContent;
    expect(firstTeamAfter?.includes(firstTeamBefore?.includes("Beta") ? "Beta" : "Alpha")).toBe(true);

    await user.click(screen.getByRole("radio", { name: "Club ease" }));
    expect(
      screen.getByRole("columnheader", { name: /Avg Club ease \(GW1-10\)/ }),
    ).toBeInTheDocument();
    const easeGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(easeGw6).toHaveAttribute("data-bucket", "much-easier");
    expect(easeGw6!.className).toContain("bg-green");
    expect(easeGw6).toHaveTextContent(/GW6 · 132/);
    expect(easeGw6).toHaveAccessibleName(/fixture-ease-proxy-v1/i);

    await user.click(screen.getByRole("radio", { name: "Official FDR" }));
    expect(screen.getByRole("columnheader", { name: "Avg FDR" })).toBeInTheDocument();
    const fdrGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(fdrGw6).toHaveAttribute("data-bucket", "easier");
    expect(fdrGw6!.className).toContain("bg-green");
    expect(fdrGw6).toHaveTextContent("GW6 · FDR 2");
    expect(fdrGw6).toHaveAccessibleName(/current official FDR 2/i);

    await user.click(within(alphaRow!).getByRole("button", { name: "Expand recent results" }));
    expect(screen.getByRole("table", { name: "Alpha recent results" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "15 GWs" }));
    expect(screen.getByRole("columnheader", { name: "GW15" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "GW16" })).not.toBeInTheDocument();
  });

  it("keeps every modelled, blank, and schedule-only GW card in identical fixed columns", async () => {
    const user = userEvent.setup();
    const { container } = render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    const expectFixedGameweekLayout = (expectedColumnCount: number) => {
      const headers = screen
        .getAllByRole("columnheader")
        .filter((header) => header.getAttribute("data-column-kind") === "gameweek");
      expect(headers).toHaveLength(expectedColumnCount);
      for (const header of headers) {
        expect(header).toHaveClass("w-20", "min-w-20", "max-w-20");
      }

      const gameweekCells = [
        ...container.querySelectorAll<HTMLElement>('td[data-column-kind="gameweek"]'),
      ];
      expect(gameweekCells.length).toBeGreaterThan(0);
      for (const cell of gameweekCells) {
        expect(cell).toHaveClass("w-20", "min-w-20", "max-w-20");
      }

      const modelledCards = screen.queryAllByTestId("chip");
      const blankCards = screen.queryAllByTestId("blank-slot");
      const scheduleCards = screen.queryAllByTestId("schedule-chip");
      expect(modelledCards.length).toBeGreaterThan(0);
      for (const card of [...modelledCards, ...blankCards, ...scheduleCards]) {
        expect(card).toHaveClass("w-16", "min-w-16", "max-w-16");
      }
      for (const stack of screen.queryAllByTestId("fixture-card-stack")) {
        expect(stack).toHaveClass("w-16", "min-w-16", "max-w-16");
      }
    };

    expectFixedGameweekLayout(5);

    await user.click(screen.getByRole("radio", { name: "10 GWs" }));
    expectFixedGameweekLayout(10);
    const gw6Proxy = screen
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(gw6Proxy).toHaveTextContent(/GW6 · 90/);
    expect(gw6Proxy).toHaveAccessibleName(/selected-vintage opponent strength proxy/i);

    await user.click(screen.getByRole("radio", { name: "15 GWs" }));
    expectFixedGameweekLayout(15);
    expect(screen.getByRole("columnheader", { name: "GW15" })).toHaveClass(
      "w-20",
      "min-w-20",
      "max-w-20",
    );
  });

  it("shows the shared rolling window, DGWs, nulls, and explicit season isolation", async () => {
    const user = userEvent.setup();
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    expect(screen.getByRole("combobox", { name: "Actual scope" })).toHaveTextContent("Rolling 5");
    const alphaRow = screen.getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    await user.click(within(alphaRow!).getByRole("button", { name: "Expand recent results" }));

    const currentDetail = screen.getByTestId("team-actual-details-101");
    expect(currentDetail).toHaveTextContent(
      "shared window 2026-27 GW6, 2026-27 GW5, 2026-27 GW4, 2026-27 GW3, 2026-27 GW2",
    );
    const currentFixtures = [
      ...currentDetail.querySelectorAll<HTMLElement>("[data-actual-fixture]"),
    ];
    expect(currentFixtures.map((row) => row.dataset.actualFixture)).toEqual([
      "602",
      "601",
      "500",
      "400",
      "300",
      "200",
    ]);
    expect(currentFixtures[0]).toHaveTextContent("GAM (A)");
    expect(currentFixtures[1]).toHaveTextContent("GW6 · 2026-09-19");
    expect(currentFixtures[1]).toHaveTextContent("BET (H)");
    expect(currentFixtures[1]).toHaveTextContent(/0\s*0\s*–\s*–\s*–\s*–/);
    expect(within(currentDetail).queryByText(/lambda|ease|probability|modelled|schedule only/i)).toBeNull();

    screen.getByRole("combobox", { name: "Actual scope" }).focus();
    await user.keyboard("{Enter}");
    await user.click(await screen.findByRole("option", { name: "2025-26" }));
    await waitFor(() => expect(screen.queryByTestId("team-actual-details-101")).toBeNull());
    const alphaPriorRow = screen.getByText("Alpha").closest("tr");
    await user.click(
      within(alphaPriorRow!).getByRole("button", { name: "Expand recent results" }),
    );
    const priorDetail = screen.getByTestId("team-actual-details-101");
    expect(priorDetail).toHaveTextContent("2025-26");
    expect(priorDetail).toHaveTextContent("GW38");
    expect(priorDetail).toHaveTextContent("OME (A)");
    expect(priorDetail).not.toHaveTextContent("GW6");
  });

  it("continues the rolling five through the prior season without per-club backfill", async () => {
    vi.mocked(loadTeamActuals).mockResolvedValueOnce({
      ...teamActuals,
      teams: [
        {
          ...teamActuals.teams[0],
          actuals: [
            actual({ gw: 35, fixture: 350, kickoff_time: "2026-05-03T15:00:00+00:00" }),
            actual({ gw: 36, fixture: 360, kickoff_time: "2026-05-10T15:00:00+00:00" }),
            actual({ gw: 37, fixture: 370, kickoff_time: "2026-05-17T15:00:00+00:00" }),
            teamActuals.teams[0].actuals[0],
          ],
        },
        {
          season: "2026-27",
          team_code: 101,
          actuals: [actual({ gw: 1, fixture: 100 })],
        },
      ],
    });
    const user = userEvent.setup();
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    const alphaRow = screen.getByText("Alpha").closest("tr");
    await user.click(within(alphaRow!).getByRole("button", { name: "Expand recent results" }));
    const detail = screen.getByTestId("team-actual-details-101");
    expect(detail).toHaveTextContent(
      "shared window 2026-27 GW1, 2025-26 GW38, 2025-26 GW37, 2025-26 GW36, 2025-26 GW35",
    );
    expect(
      [...detail.querySelectorAll<HTMLElement>("[data-actual-fixture]")].map(
        (row) => row.dataset.actualFixture,
      ),
    ).toEqual(["100", "380", "370", "360", "350"]);

    const betaRow = screen.getByText("Beta").closest("tr");
    await user.click(within(betaRow!).getByRole("button", { name: "Expand recent results" }));
    expect(screen.getByTestId("team-actual-details-102")).toHaveTextContent(
      /No ended results are available/,
    );

    screen.getByRole("combobox", { name: "Actual scope" }).focus();
    await user.keyboard("{Enter}");
    await user.click(await screen.findByRole("option", { name: "2026-27" }));
    const alphaCurrentRow = screen.getByText("Alpha").closest("tr");
    await user.click(
      within(alphaCurrentRow!).getByRole("button", { name: "Expand recent results" }),
    );
    const currentOnlyDetail = screen.getByTestId("team-actual-details-101");
    expect(currentOnlyDetail).toHaveTextContent("shared window 2026-27 GW1");
    expect(currentOnlyDetail).not.toHaveTextContent("2025-26 GW38");
  });

  it("explains when the export carries no recorded vintage", async () => {
    vi.mocked(loadFixtureMatrix).mockResolvedValueOnce({
      teams: [],
      schedule: { ...schedule, teams: [] },
      manifest: null,
      easeIndexFormulaVersion: "fixture-ease-v1",
    });
    render(<FixtureMatrixPage />);
    expect(await screen.findByText(/No recorded forecast vintages/)).toBeInTheDocument();
  });
});
