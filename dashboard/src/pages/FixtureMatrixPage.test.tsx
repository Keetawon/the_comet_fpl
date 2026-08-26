// Page smoke: the Fixture matrix pivot renders from a read model -- one row per club of
// the selected vintage, per-GW chip columns with blank slots, the three colour sources,
// default sort by average ease (easiest first), and opponent-strength colouring direction
// (a weak opponent colours green, a strong opponent red, regardless of the row club).

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw } from "@/data/load";
import sample from "@/data/sampleFixtureMatrix.json";
import nextGwSample from "@/data/sampleNextGw.json";
import type { FixtureScheduleOverlay, NextGwPlan } from "@/data/types";
import { FixtureMatrixPage } from "./FixtureMatrixPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];
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
}));

beforeEach(() => {
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: sample.teams,
    schedule,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
});

describe("FixtureMatrixPage", () => {
  it("renders one row per club with per-GW chips, blank slots, and all colour sources", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Enter Fixture matrix table fullscreen" }),
    ).toBeInTheDocument();
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

  it("sorts by average ease by default, easiest schedule first", async () => {
    const { container } = render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const rows = container.querySelectorAll("tbody > tr");
    const firstTeamRow = [...rows].find(
      (r) => r.textContent?.includes("Beta") || r.textContent?.includes("Alpha"),
    );
    // Beta's only measured fixture averages 118.6 vs Alpha's 106.5, so Beta leads.
    expect(firstTeamRow!.textContent).toContain("Beta");
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
    const betaBefore = screen.getByText("Beta").closest("tr");
    expect(betaBefore).not.toBeNull();
    expect(within(betaBefore!).getByText("118.6")).toBeInTheDocument();

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
    expect(alphaGw6).toHaveTextContent(/GW6 · \d+/);
    expect(alphaGw6).toHaveAccessibleName(
      /derived from selected-vintage GW1-GW4 team lambdas, not a GW6 forecast/i,
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
    expect(within(betaAfter!).getByText("118.6")).toBeInTheDocument();
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
    const easeGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(easeGw6).toHaveAttribute("data-bucket", "much-easier");
    expect(easeGw6!.className).toContain("bg-green");
    expect(easeGw6).toHaveTextContent(/GW6 · \d+/);
    expect(easeGw6).toHaveAccessibleName(/fixture-ease-proxy-v1/i);

    await user.click(screen.getByRole("radio", { name: "Official FDR" }));
    const fdrGw6 = within(alphaRow!)
      .getAllByTestId("schedule-chip")
      .find((chip) => chip.dataset.gw === "6" && chip.textContent?.includes("BET"));
    expect(fdrGw6).toHaveAttribute("data-bucket", "easier");
    expect(fdrGw6!.className).toContain("bg-green");
    expect(fdrGw6).toHaveTextContent("GW6 · FDR 2");
    expect(fdrGw6).toHaveAccessibleName(/current official FDR 2/i);

    await user.click(within(alphaRow!).getByRole("button", { name: "Expand fixtures" }));
    expect(screen.getAllByText("Schedule only").length).toBeGreaterThan(0);

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
    expect(gw6Proxy).toHaveTextContent(/GW6 · \d+/);
    expect(gw6Proxy).toHaveAccessibleName(/selected-vintage opponent strength proxy/i);

    await user.click(screen.getByRole("radio", { name: "15 GWs" }));
    expectFixedGameweekLayout(15);
    expect(screen.getByRole("columnheader", { name: "GW15" })).toHaveClass(
      "w-20",
      "min-w-20",
      "max-w-20",
    );
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
