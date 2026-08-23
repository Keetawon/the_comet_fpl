// Plan builder (wizard v2): custom rules and their exact result stay here. The shared player
// picker supports mutually-exclusive green locks and red exclusions; Next GW remains the
// platform-owned recommendation and is never replaced by a custom solve.

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import {
  fetchManagerTeam,
  fetchManagerTeamCapture,
  fetchPlanStatus,
  solveManagerPlan,
  solvePlan,
  type ManagerTeamPreview,
  type PlanSummary,
} from "@/lib/planServer";
import { reloadPublishedReadModels } from "@/lib/readModelReload";
import playersSample from "@/data/samplePlayers.json";
import nextGwSample from "@/data/sampleNextGw.json";
import auditSample from "@/data/sampleOptimizerAudit.json";
import type { NextGwPlan, OptimizerAuditData, PlanPlayer, PlayerRecord } from "@/data/types";
import { PlanBuilderPage } from "./PlanBuilderPage";

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadNextGw: vi.fn(),
  loadOptimizerAudit: vi.fn(),
}));

vi.mock("@/lib/planServer", () => ({
  PLAN_SERVER_START_COMMAND: ".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server",
  fetchManagerTeam: vi.fn(),
  fetchManagerTeamCapture: vi.fn(),
  fetchPlanStatus: vi.fn(),
  solveManagerPlan: vi.fn(),
  solvePlan: vi.fn(),
}));

vi.mock("@/lib/readModelReload", () => ({
  reloadPublishedReadModels: vi.fn(),
}));

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];
const audit: OptimizerAuditData = auditSample as unknown as OptimizerAuditData;
const samplePlayers = playersSample.players as unknown as PlayerRecord[];

const clonePlayer = (
  base: PlayerRecord,
  code: number,
  webName: string,
  position: PlayerRecord["position"],
): PlayerRecord => ({
  ...base,
  code,
  web_name: webName,
  position,
  team_code: 200 + (code % 10),
  team_short_name: "T" + String(code % 10),
  now_cost: 40,
});

// The real picker receives the full forecast roster. Keep the fixture compact while supplying
// enough players to complete every frozen position quota, so the review edge is honestly enabled.
const builderPlayers: PlayerRecord[] = [
  samplePlayers[0],
  samplePlayers[1],
  clonePlayer(samplePlayers[1], 9, "Keeper Three", "GK"),
  clonePlayer(samplePlayers[1], 10, "Keeper Two", "GK"),
  ...Array.from({ length: 5 }, (_, index) =>
    clonePlayer(samplePlayers[0], 11 + index, "Defender " + (index + 1), "DEF"),
  ),
  ...Array.from({ length: 4 }, (_, index) =>
    clonePlayer(samplePlayers[0], 16 + index, "Midfielder " + (index + 1), "MID"),
  ),
  ...Array.from({ length: 3 }, (_, index) =>
    clonePlayer(samplePlayers[0], 20 + index, "Forward " + (index + 1), "FWD"),
  ),
];

const makePlanPlayer = (
  code: number,
  webName: string,
  position: string,
  role: PlanPlayer["role"],
  expectedPoints: number,
  options: {
    benchOrder?: number;
    captain?: boolean;
    viceCaptain?: boolean;
  } = {},
): PlanPlayer => ({
  ...plans[0].weeks[0].players[0],
  code,
  web_name: webName,
  position,
  team_code: 100 + code,
  team_short_name: `T${code}`,
  now_cost: 40 + code,
  role,
  bench_order_index: options.benchOrder ?? null,
  is_captain: options.captain ?? false,
  is_vice_captain: options.viceCaptain ?? false,
  transferred_in: false,
  transferred_out: false,
  expected_points: expectedPoints,
});

const customGw1Players: PlanPlayer[] = [
  makePlanPlayer(1, "Alpha", "MID", "starting_xi", 7.4, { captain: true }),
  makePlanPlayer(2, "Beta", "GK", "starting_xi", 3.9, { viceCaptain: true }),
  makePlanPlayer(4, "Delta", "DEF", "starting_xi", 3.8),
  makePlanPlayer(5, "Echo", "DEF", "starting_xi", 3.7),
  makePlanPlayer(6, "Foxtrot", "DEF", "starting_xi", 3.6),
  makePlanPlayer(7, "Hotel", "DEF", "starting_xi", 3.5),
  makePlanPlayer(8, "India", "MID", "starting_xi", 3.4),
  makePlanPlayer(9, "Juliet", "MID", "starting_xi", 3.3),
  makePlanPlayer(10, "Kilo", "MID", "starting_xi", 3.2),
  makePlanPlayer(11, "Lima", "FWD", "starting_xi", 3.1),
  makePlanPlayer(12, "Mike", "FWD", "starting_xi", 3.0),
  makePlanPlayer(13, "Bench Keeper", "GK", "bench_goalkeeper", 2.4),
  makePlanPlayer(3, "Gamma", "FWD", "bench_outfield", 2.1, { benchOrder: 1 }),
  makePlanPlayer(14, "Bench Two", "MID", "bench_outfield", 2.3, { benchOrder: 2 }),
  makePlanPlayer(15, "Bench Three", "DEF", "bench_outfield", 2.2, { benchOrder: 3 }),
];

const replacement = makePlanPlayer(99, "Replacement", "MID", "starting_xi", 5.0, {
  captain: true,
});
const customPlanWeeks = Array.from({ length: 5 }, (_, index) => {
  const gw = index + 1;
  if (gw === 1) {
    return {
      ...plans[0].weeks[0],
      gw,
      captain_code: 1,
      vice_captain_code: 2,
      players: customGw1Players,
    };
  }
  return {
    ...plans[0].weeks[0],
    gw,
    captain_code: 99,
    vice_captain_code: 2,
    players: [
      ...customGw1Players
        .filter((player) => player.code !== 1)
        .map((player) => ({ ...player, transferred_in: false })),
      { ...replacement, transferred_in: gw === 2 },
    ],
  };
});

const customPlayerXp: NextGwPlan["player_xp"] = Object.fromEntries(
  customGw1Players.map((player) => [
    String(player.code),
    Object.fromEntries(
      Array.from({ length: 5 }, (_, index) => [
        String(index + 1),
        Number(((player.expected_points ?? 0) - index * 0.1).toFixed(1)),
      ]),
    ),
  ]),
);
customPlayerXp["1"] = { "1": 7.4, "2": 6.1, "3": 5.5, "4": 4.9, "5": 6.3 };
customPlayerXp["2"] = { "1": 3.9, "2": 3.4, "3": 3.8, "4": 3.1, "5": 4.0 };
customPlayerXp["3"] = { "1": 2.1, "2": null, "3": 2.4, "4": 2.8, "5": 2.2 };
customPlayerXp["99"] = { "1": 5.0, "2": 5.1, "3": 5.2, "4": 5.3, "5": 5.4 };

const customPlan: NextGwPlan = {
  ...plans[0],
  optimizer_run_id: "solved-custom-run",
  decision_sha256: "solved-custom-decision",
  plan_kind: "user_custom",
  display_label: "Your plan — 1 lock, 1 exclusion",
  policy: {
    locked_codes: [1],
    excluded_codes: [2],
    min_bench_appearance: 0.25,
  },
  weeks: customPlanWeeks,
  player_xp: customPlayerXp,
};

const managerOwnedCodes = [1, 2, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22];
const managerPreview: ManagerTeamPreview = {
  capture_id: "manager-capture-001",
  captured_at: "2026-08-23T09:15:00Z",
  manager_id: 1234567,
  entry_name: "Test Eleven",
  picks_event: 1,
  planning_gw: 2,
  bank_tenths: 15,
  squad_selling_value_tenths: 985,
  free_transfers_available: 0,
  free_transfers_source: "reconstructed_transfer_history",
  existing_hit_points: 4,
  players: managerOwnedCodes.map((code, index) => {
    const player = builderPlayers.find((candidate) => candidate.code === code);
    if (!player) throw new Error(`Missing manager preview player ${code}`);
    return {
      element_id: 1000 + code,
      code,
      web_name: player.web_name,
      position: player.position as ManagerTeamPreview["players"][number]["position"],
      team_id: index + 1,
      team_code: player.team_code,
      now_cost: player.now_cost ?? 65,
      purchase_price: index === 0 ? 87 : 62,
      selling_price: index === 0 ? 89 : 64,
    };
  }),
};

const managerPlanWeeks = customPlanWeeks.map((week, index) => ({
  ...week,
  gw: index + 2,
}));
const managerPlayerXp: NextGwPlan["player_xp"] = Object.fromEntries(
  Object.entries(customPlayerXp).map(([code, gameweeks]) => [
    code,
    Object.fromEntries(
      Object.entries(gameweeks).map(([gw, expectedPoints]) => [
        String(Number(gw) + 1),
        expectedPoints,
      ]),
    ),
  ]),
);
const managerPlan: NextGwPlan = {
  ...customPlan,
  optimizer_run_id: "manager-solved-run",
  decision_sha256: "manager-solved-decision",
  display_label: "Your imported-team transfer plan",
  gw_from: 2,
  gw_to: 6,
  policy: {
    locked_codes: [1],
    excluded_codes: [10],
    min_bench_appearance: 0,
  },
  weeks: managerPlanWeeks,
  player_xp: managerPlayerXp,
};

const solvedManagerSummary: PlanSummary = {
  optimizer_run_id: managerPlan.optimizer_run_id,
  decision_sha256: managerPlan.decision_sha256,
  gw: 2,
  gw_expected_points: 61.2,
  horizon_expected_points: 308.4,
  hit_points: 4,
  squad_cost_tenths: 1007,
  captain: "Alpha",
  vice_captain: "Beta",
  manager_capture_id: managerPreview.capture_id,
  manager_entry_name: managerPreview.entry_name,
  manager_planning_gw: managerPreview.planning_gw,
  manager_existing_hit_points: managerPreview.existing_hit_points,
  manager_initial_free_transfers: 0,
  manager_bank_tenths: managerPreview.bank_tenths,
  manager_squad_selling_value_tenths: managerPreview.squad_selling_value_tenths,
  manager_weeks: [
    {
      gw: 2,
      transfers_in: [{ code: 99, web_name: "Replacement" }],
      transfers_out: [{ code: 16, web_name: "Midfielder 1" }],
      free_transfers_before: 0,
      free_transfers_after: 0,
      hit_points: 4,
      bank_before_tenths: 15,
      bank_after_tenths: 7,
    },
    {
      gw: 3,
      transfers_in: [],
      transfers_out: [],
      free_transfers_before: 1,
      free_transfers_after: 2,
      hit_points: 0,
      bank_before_tenths: 7,
      bank_after_tenths: 7,
    },
  ],
};

const readyRuntime = {
  python_executable: "D:\\repo\\.venv\\Scripts\\python.exe",
  python_prefix: "D:\\repo\\.venv",
  pulp_package_version: "3.3.0",
  cbc_binary_version: "2.10.3",
  solver_ready: true,
} as const;

beforeEach(() => {
  vi.unstubAllEnvs();
  vi.mocked(loadPlayers).mockResolvedValue({ players: builderPlayers, manifest: null });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  vi.mocked(fetchManagerTeam).mockReset();
  vi.mocked(fetchManagerTeamCapture).mockReset();
  vi.mocked(fetchPlanStatus).mockResolvedValue(null); // offline unless a test says otherwise
  vi.mocked(solveManagerPlan).mockReset();
  vi.mocked(solvePlan).mockReset();
  vi.mocked(reloadPublishedReadModels).mockReset();
  window.localStorage.clear();
  window.location.hash = "";
});

describe("PlanBuilderPage", () => {
  it("keeps the hosted build read-only and never probes the local plan server", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    vi.mocked(fetchPlanStatus).mockClear();
    const user = userEvent.setup();

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText(/Build from scratch/));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(
      screen.getByRole("heading", { name: "Optimization stays on your trusted machine" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/public dashboard is read-only for optimization/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Squad draft" })).toHaveAttribute(
      "href",
      "#squad-draft",
    );
    expect(screen.queryByLabelText("Solve")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Plan server token/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    expect(fetchPlanStatus).not.toHaveBeenCalled();
    expect(solvePlan).not.toHaveBeenCalled();
  });

  it("starts with both entry cards and marks manager import ready on local development", async () => {
    render(<PlanBuilderPage />);
    expect(await screen.findByText("Import my team")).toBeInTheDocument();
    expect(screen.getByText("Ready on local development")).toBeInTheDocument();
    expect(screen.getByText(/banked free transfers and -4 hits accounted/)).toBeInTheDocument();
    expect(screen.getByText("Build from scratch →")).toBeInTheDocument();
  });

  it("requires a valid manager id and an exact capture before continuing", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchManagerTeam).mockResolvedValue(managerPreview);

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Import my team"));

    const continueButton = screen.getByRole("button", {
      name: /Choose locked and excluded players/,
    });
    expect(continueButton).toBeDisabled();
    const input = await screen.findByLabelText("FPL manager id");
    await user.type(input, "12a4");
    expect(screen.getByText(/Digits only/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Get your team" })).toBeDisabled();
    expect(continueButton).toBeDisabled();

    await user.clear(input);
    await user.type(input, "1234567");
    await user.click(screen.getByRole("button", { name: "Get your team" }));

    expect(fetchManagerTeam).toHaveBeenCalledWith("1234567", "");
    expect(await screen.findByText("Test Eleven")).toBeInTheDocument();
    expect(screen.getByText(/Public squad after GW1/)).toHaveTextContent(
      "planning GW2 · 15 players reconciled",
    );
    expect(screen.getByText("Bank").parentElement).toHaveTextContent("£1.5m");
    expect(screen.getByText("Selling value").parentElement).toHaveTextContent("£98.5m");
    expect(screen.getByText("Remaining FT").parentElement).toHaveTextContent("0");
    expect(screen.getByText("Already-paid hits").parentElement).toHaveTextContent("-4");
    expect(continueButton).toBeEnabled();

    await user.click(continueButton);
    expect(screen.getByLabelText("Search player")).toBeInTheDocument();
    expect(window.localStorage.getItem("fpl-manager-id")).toBe("1234567");
  });

  it("solves the imported squad with owned-only locks, any-player exclusions, hits, and both draft handoffs", async () => {
    const user = userEvent.setup();
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], managerPlan, plans[1]],
    });
    vi.mocked(fetchManagerTeam).mockResolvedValue(managerPreview);
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: readyRuntime,
    });
    vi.mocked(solveManagerPlan).mockResolvedValue(solvedManagerSummary);

    const firstRender = render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Import my team"));
    await user.type(screen.getByLabelText("FPL manager id"), "1234567");
    await user.click(screen.getByRole("button", { name: "Get your team" }));
    await user.click(
      await screen.findByRole("button", {
        name: /Choose locked and excluded players/,
      }),
    );

    expect(screen.getByText("Imported manager transfer state")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^Budget meter/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/cheapest position fill/)).not.toBeInTheDocument();

    const search = screen.getByRole("textbox", { name: "Search player" });
    await user.type(search, "Keeper Two");
    let keeperTwo = screen.getByRole("button", { name: /Keeper Two/ });
    expect(keeperTwo).toBeDisabled();
    expect(keeperTwo).toHaveTextContent("not in imported squad");

    await user.clear(search);
    await user.type(search, "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    expect(screen.getByText("locked")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Exclude" }));
    await user.clear(search);
    await user.type(search, "Keeper Two");
    keeperTwo = screen.getByRole("button", { name: /Keeper Two/ });
    expect(keeperTwo).toBeEnabled();
    await user.click(keeperTwo);
    expect(keeperTwo).toHaveTextContent("excluded");

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Remaining free transfers" }),
      "0",
    );
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("plan server online")).toBeInTheDocument();
    expect(screen.queryByText(/headroom .*cheapest position fill/)).not.toBeInTheDocument();
    expect(screen.getByText(/Imported public squad:/).parentElement).toHaveTextContent(
      "selling value £98.5m · cash £1.5m",
    );
    expect(screen.getByText(/Effective remaining FT:/)).toHaveTextContent(
      "0 (user override) · already-paid hits -4",
    );

    await user.click(screen.getByRole("button", { name: "Solve now with my rules" }));
    await waitFor(() =>
      expect(solveManagerPlan).toHaveBeenCalledWith(
        {
          captureId: managerPreview.capture_id,
          locks: [1],
          excludes: [10],
          minBenchAppearance: null,
          freeTransfersOverride: 0,
        },
        expect.any(Function),
        "",
      ),
    );

    expect(await screen.findByText("Your plan — GW2")).toBeInTheDocument();
    const recommendation = screen.getByRole("region", {
      name: "Manager transfer recommendations",
    });
    expect(within(recommendation).getByText("sunk hits -4")).toBeInTheDocument();
    expect(within(recommendation).getByText("new hits -4")).toBeInTheDocument();
    const gw2 = within(recommendation).getByText("GW2").closest("li");
    expect(gw2).not.toBeNull();
    expect(gw2).toHaveTextContent(
      "FT 0 → 0 · bank £1.5m → £0.7m · hit -4",
    );
    expect(within(gw2!).getByText("OUT").parentElement).toHaveTextContent(
      "Midfielder 1",
    );
    expect(within(gw2!).getByText("IN").parentElement).toHaveTextContent("Replacement");
    const gw3 = within(recommendation).getByText("GW3").closest("li");
    expect(gw3).toHaveTextContent("FT 1 → 2 · bank £0.7m → £0.7m");
    expect(within(gw3!).getByText(/HOLD — bank the free transfer/)).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Forward suggested team to Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=manager-solved-run&source=optimized",
    );
    expect(
      screen.getByRole("link", { name: "Use captured current team in Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=manager-solved-run&source=manager_current&manager_capture_id=manager-capture-001",
    );

    expect(window.localStorage.getItem("fpl-solved-plan")).toBe("manager-solved-run");
    expect(
      JSON.parse(
        window.localStorage.getItem("fpl-solved-manager-result-v1") ?? "{}",
      ),
    ).toMatchObject({
      version: 1,
      optimizerRunId: "manager-solved-run",
      managerCaptureId: managerPreview.capture_id,
      summary: {
        optimizer_run_id: "manager-solved-run",
        manager_capture_id: managerPreview.capture_id,
        hit_points: 4,
        manager_existing_hit_points: 4,
      },
    });
    expect(window.localStorage.getItem("fpl-solved-manager-capture")).toBeNull();
    expect(window.localStorage.getItem("fpl-solved-manager-summary")).toBeNull();
    expect(window.localStorage.getItem("fpl-plan-request")).toBeNull();
    expect(window.location.hash).toBe(
      "#plan-builder?run=manager-solved-run&manager_capture_id=manager-capture-001",
    );
    expect(reloadPublishedReadModels).toHaveBeenCalledTimes(1);

    firstRender.unmount();
    vi.mocked(fetchManagerTeamCapture).mockResolvedValue(managerPreview);
    render(<PlanBuilderPage />);
    expect(await screen.findByText("Your plan — GW2")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Manager transfer recommendations" }),
    ).toHaveTextContent("HOLD — bank the free transfer");
    expect(
      screen.getByRole("link", { name: "Use captured current team in Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=manager-solved-run&source=manager_current&manager_capture_id=manager-capture-001",
    );
    expect(fetchManagerTeam).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Edit and solve again" }));
    expect(await screen.findByText("Imported manager transfer state")).toBeInTheDocument();
    expect(fetchManagerTeamCapture).toHaveBeenCalledWith(
      managerPreview.capture_id,
      "",
    );
    expect(screen.getByRole("button", { name: /Next: Review & run/ })).toBeEnabled();
  });

  it("caps owned manager exclusions at the current first-week transfer depth", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchManagerTeam).mockResolvedValue(managerPreview);

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Import my team"));
    await user.type(screen.getByLabelText("FPL manager id"), "1234567");
    await user.click(screen.getByRole("button", { name: "Get your team" }));
    await user.click(
      await screen.findByRole("button", {
        name: /Choose locked and excluded players/,
      }),
    );
    await user.click(screen.getByRole("radio", { name: "Exclude" }));
    const search = screen.getByRole("textbox", { name: "Search player" });
    for (const name of ["Alpha", "Beta"]) {
      await user.clear(search);
      await user.type(search, name);
      await user.click(screen.getByRole("button", { name: new RegExp(name) }));
    }

    expect(screen.getByText(/Owned players forced OUT:/)).toHaveTextContent("2/2");
    await user.clear(search);
    await user.type(search, "Keeper Three");
    const thirdOwned = screen.getByRole("button", { name: /Keeper Three/ });
    expect(thirdOwned).toBeDisabled();
    expect(thirdOwned).toHaveTextContent("first-week transfer depth (2)");

    await user.clear(search);
    await user.type(search, "Keeper Two");
    expect(screen.getByRole("button", { name: /Keeper Two/ })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(
      screen.getByRole("alert", { name: "" }),
    ).toHaveTextContent(/Manual manager-result opening is unavailable/);
    expect(
      screen.queryByRole("textbox", { name: "Published optimizer run id" }),
    ).not.toBeInTheDocument();
  });

  it("does not attach a stored manager capture to a different custom run", async () => {
    window.location.hash = "#plan-builder?run=" + customPlan.optimizer_run_id;
    window.localStorage.setItem("fpl-solved-plan", managerPlan.optimizer_run_id);
    window.localStorage.setItem(
      "fpl-solved-manager-result-v1",
      JSON.stringify({
        version: 1,
        optimizerRunId: managerPlan.optimizer_run_id,
        managerCaptureId: managerPreview.capture_id,
        summary: solvedManagerSummary,
      }),
    );
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], customPlan, managerPlan, plans[1]],
    });

    render(<PlanBuilderPage />);

    expect(await screen.findByText("Your plan — GW1")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Forward team to Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=solved-custom-run",
    );
    expect(
      screen.queryByRole("link", { name: "Use captured current team in Squad Draft" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Manager transfer recommendations" }),
    ).not.toBeInTheDocument();
  });

  it("discards a malformed stored manager summary without losing an explicit run/capture handoff", async () => {
    window.location.hash =
      "#plan-builder?run=manager-solved-run&manager_capture_id=manager-capture-001";
    window.localStorage.setItem(
      "fpl-solved-manager-result-v1",
      JSON.stringify({
        version: 1,
        optimizerRunId: managerPlan.optimizer_run_id,
        managerCaptureId: managerPreview.capture_id,
        summary: {
          optimizer_run_id: managerPlan.optimizer_run_id,
          manager_capture_id: managerPreview.capture_id,
          manager_weeks: {},
        },
      }),
    );
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], managerPlan, plans[1]],
    });

    render(<PlanBuilderPage />);

    expect(await screen.findByText("Your plan — GW2")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Manager transfer recommendations" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Use captured current team in Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=manager-solved-run&source=manager_current&manager_capture_id=manager-capture-001",
    );
  });

  it("locks a searched player in green, advances to review, and emits the exact command", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    const search = screen.getByRole("textbox", { name: "Search player" });
    await user.type(search, "Alpha");
    const alpha = screen.getByRole("button", { name: /Alpha/ });
    await user.click(alpha);
    expect(screen.getByText("locked")).toBeInTheDocument();
    expect(alpha.className).toContain("emerald");
    // the shared filter bar is present (team/price/minutes/availability, no form window)
    expect(screen.getByRole("combobox", { name: "Team filter" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Minimum price in millions" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Form window" })).not.toBeInTheDocument();
    // threshold + budget meter live on the rules screen
    await user.click(screen.getByText("25%"));
    expect(screen.getByRole("img", { name: /^Budget meter/ })).toBeInTheDocument();
    expect(screen.getByText(/headroom £/)).toBeInTheDocument();
    // advancing to review keeps the lock and shows the command with both flags
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(screen.getByRole("button", { name: "Unlock Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    const pre = document.querySelector("pre")!; // the command block is the page's only <pre>
    expect(pre.textContent).toContain("--lock 1");
    expect(pre.textContent).toContain("--plan-origin user_custom");
    expect(pre.textContent).toContain("--min-bench-appearance 0.25");
    // The command is runnable as-is (dev-latest convention paths, not placeholders) and the
    // v2 request is persisted so an interrupted manual solve can resume in Plan Builder.
    const saved = JSON.parse(window.localStorage.getItem("fpl-plan-request") ?? "{}") as {
      version: number;
      locks: unknown[];
      excludes: unknown[];
      command: string;
    };
    expect(saved.version).toBe(2);
    expect(saved.locks).toHaveLength(1);
    expect(saved.excludes).toHaveLength(0);
    expect(saved.command).toContain("dev-latest\\gw1_5_default.jsonl");
    expect(saved.command).toContain("--min-bench-appearance 0.25");
    expect(saved.command).toMatch(/--output D:\\tmp\\gw1\\dev-latest\\plan_my_rules_[a-z0-9]+\.json/i);
    expect(saved.command).not.toContain("plan_my_rules.json");
    // removing the lock through the chip drops it from the command AND the saved request
    await user.click(screen.getByRole("button", { name: "Unlock Alpha" }));
    expect(pre.textContent).not.toContain("--lock 1");
    const after = JSON.parse(window.localStorage.getItem("fpl-plan-request") ?? "{}") as {
      locks: unknown[];
      excludes: unknown[];
      command: string;
    };
    expect(after.locks).toHaveLength(0);
    expect(after.excludes).toHaveLength(0);
    expect(after.command).not.toContain("--lock 1");
  });

  it("uses the same picker for red exclusions and prevents lock/exclude overlap", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));

    const search = screen.getByRole("textbox", { name: "Search player" });
    await user.type(search, "Alpha");
    const alpha = screen.getByRole("button", { name: /Alpha/ });
    await user.click(alpha);
    expect(alpha.className).toContain("emerald");

    await user.click(screen.getByRole("radio", { name: "Exclude" }));
    // A lock cannot silently become an exclusion; the user must remove the lock first.
    expect(alpha).toBeDisabled();
    expect(alpha).toHaveTextContent("locked");
    expect(alpha.className).toContain("emerald");

    await user.clear(search);
    await user.type(search, "Beta");
    const beta = screen.getByRole("button", { name: /Beta/ });
    await user.click(beta);
    expect(screen.getByText("excluded")).toBeInTheDocument();
    expect(beta.className).toContain("red");
    expect(screen.getByText("Excluded 1/15")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(screen.getByRole("button", { name: "Unlock Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove exclusion Beta" })).toBeInTheDocument();
    const command = document.querySelector("pre")?.textContent ?? "";
    expect(command).toContain("--lock 1");
    expect(command).toContain("--exclude 2");

    const saved = JSON.parse(window.localStorage.getItem("fpl-plan-request") ?? "{}") as {
      locks: { code: number }[];
      excludes: { code: number }[];
    };
    expect(saved.locks.map((player) => player.code)).toEqual([1]);
    expect(saved.excludes.map((player) => player.code)).toEqual([2]);
  });

  it("caps exclusions at 15 and disables a sixteenth selection", async () => {
    const user = userEvent.setup();
    const avoidPlayers = Array.from({ length: 16 }, (_, index) =>
      clonePlayer(samplePlayers[0], 100 + index, "Avoid " + String(index + 1).padStart(2, "0"), "MID"),
    );
    vi.mocked(loadPlayers).mockResolvedValue({
      players: [...builderPlayers, ...avoidPlayers],
      manifest: null,
    });
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("radio", { name: "Exclude" }));
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Avoid");

    for (let index = 1; index <= 15; index++) {
      await user.click(
        screen.getByRole("button", {
          name: new RegExp("Avoid " + String(index).padStart(2, "0")),
        }),
      );
    }

    expect(screen.getByText("Excluded 15/15")).toBeInTheDocument();
    const sixteenth = screen.getByRole("button", { name: /Avoid 16/ });
    expect(sixteenth).toBeDisabled();
    expect(sixteenth).toHaveTextContent("max 15 exclusions");
  }, 10_000);

  it("pages through every eligible priced player and selects one beyond the first 50", async () => {
    const user = userEvent.setup();
    const pagedPlayers = Array.from({ length: 60 }, (_, index) => ({
      ...clonePlayer(
        samplePlayers[0],
        300 + index,
        "Paged Player " + String(index + 1).padStart(2, "0"),
        "MID",
      ),
      // Keep these below the compact base roster in the xP ordering. Stable player code is the
      // deterministic tie-breaker, so the later-page target is independent of browser locale.
      fixtures: [],
    }));
    vi.mocked(loadPlayers).mockResolvedValue({
      players: [...builderPlayers, ...pagedPlayers],
      manifest: null,
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));

    expect(screen.getByText(/Players 1–50 of 76/)).toBeInTheDocument();
    expect(screen.getAllByText("Page 1 of 2")).toHaveLength(2);
    const topPager = screen.getByRole("navigation", {
      name: "Player picker pages (top)",
    });
    const bottomPager = screen.getByRole("navigation", {
      name: "Player picker pages (bottom)",
    });
    expect(topPager).toHaveClass("sticky");
    expect(bottomPager).not.toHaveClass("sticky");
    expect(topPager.querySelector('[aria-live="polite"]')).toBeInTheDocument();
    expect(bottomPager.querySelector('[aria-live="polite"]')).not.toBeInTheDocument();
    expect(topPager).toHaveTextContent("showing 1–50 of 76");
    expect(bottomPager).toHaveTextContent("showing 1–50 of 76");
    expect(screen.queryByRole("button", { name: /Paged Player 60/ })).not.toBeInTheDocument();
    expect(within(bottomPager).getByRole("button", { name: "Previous players" })).toBeDisabled();

    // The lower control is reachable immediately after scanning the last player; there is no
    // need to scroll back to the top to continue through the complete roster.
    await user.click(within(bottomPager).getByRole("button", { name: "Next players" }));

    expect(screen.getByText(/Players 51–76 of 76/)).toBeInTheDocument();
    expect(screen.getAllByText("Page 2 of 2")).toHaveLength(2);
    const secondPageList = screen.getByRole("list", { name: "Player candidates page 2" });
    expect(secondPageList.querySelector("button:not(:disabled)")).toHaveFocus();
    expect(
      within(screen.getByRole("navigation", { name: "Player picker pages (bottom)" })).getByRole(
        "button",
        { name: "Next players" },
      ),
    ).toBeDisabled();
    const laterPlayer = screen.getByRole("button", { name: /Paged Player 60/ });
    await user.click(laterPlayer);
    expect(laterPlayer).toHaveAttribute("aria-pressed", "true");
    expect(laterPlayer).toHaveTextContent("locked");
    expect(laterPlayer.className).toContain("emerald");

    // Searching from a later page resets to the first matching page. The off-page selection
    // remains durable and reaches the v2 optimizer request.
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Alpha");
    expect(screen.getAllByText("Page 1 of 1")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Paged Player 60/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    const saved = JSON.parse(window.localStorage.getItem("fpl-plan-request") ?? "{}") as {
      locks: { code: number }[];
      command: string;
    };
    expect(saved.locks.map((player) => player.code)).toEqual([359]);
    expect(saved.command).toContain("--lock 359");
  });

  it("never strands the user: navigation preserves rules and review links to the platform page", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await user.click(screen.getByText("25%"));
    // Back to start is navigation only: re-entering resumes with the lock intact
    await user.click(screen.getByRole("button", { name: /Back to start/ }));
    expect(screen.getByText("Build from scratch →")).toBeInTheDocument();
    await user.click(screen.getByText("Build from scratch →"));
    expect(screen.getByRole("button", { name: /Alpha/ })).toHaveAttribute("aria-pressed", "true");
    // Reset rules is the only clearing action, and it clears in place
    await user.click(screen.getByRole("button", { name: /Reset rules/ }));
    expect(screen.queryByText("locked")).not.toBeInTheDocument();
    // The review screen keeps the custom workflow in place and offers a clearly named,
    // non-destructive link to the separate platform page.
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    const platform = screen.getByRole("link", { name: /View platform suggestion/ });
    expect(platform).toHaveAttribute("href", "#next-gw");
    await user.click(screen.getByRole("button", { name: /Back to rules/ }));
    expect(screen.getByRole("textbox", { name: "Search player" })).toBeInTheDocument();
  });

  it("renders only the exact custom run carried in the URL and never falls back", async () => {
    const user = userEvent.setup();
    window.location.hash = "#plan-builder?run=" + customPlan.optimizer_run_id;
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], customPlan, plans[1]],
    });

    render(<PlanBuilderPage />);

    expect(await screen.findByText("Your plan — GW1")).toBeInTheDocument();
    expect(screen.getByText("1 locked")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Enter GW1 custom plan players table fullscreen",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 excluded")).toBeInTheDocument();
    expect(screen.getByText(/locked ·/).parentElement).toHaveTextContent("Alpha");
    expect(screen.getByText(/excluded ·/).parentElement).toHaveTextContent("Beta");
    expect(screen.getByText(/optimizer run solved-custo/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Forward team to Squad Draft" }),
    ).toHaveAttribute(
      "href",
      "#squad-draft?optimizer_run_id=solved-custom-run",
    );
    expect(
      screen.queryByRole("link", { name: "Use captured current team in Squad Draft" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Manager transfer recommendations" }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("fpl-solved-manager-capture")).toBeNull();
    expect(window.localStorage.getItem("fpl-solved-manager-summary")).toBeNull();
    expect(window.localStorage.getItem("fpl-solved-manager-result-v1")).toBeNull();
    const squadTable = screen.getByRole("table", { name: "GW1 custom squad analysis" });
    const mainRows = within(squadTable)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-player-code"));
    expect(mainRows).toHaveLength(15);
    expect(mainRows.some((row) => row.getAttribute("data-player-code") === "99")).toBe(false);
    expect(within(squadTable).getByText("Alpha").closest("tr")).toHaveClass("bg-amber-100/70");
    expect(within(squadTable).getByText("Beta").closest("tr")).toHaveClass("bg-amber-50");
    expect(within(squadTable).getByText("Gamma").closest("tr")).toHaveClass("bg-zinc-200");
    expect(within(squadTable).getByLabelText("Captain: Alpha")).toHaveAttribute("title", "Captain");
    expect(within(squadTable).getByLabelText("Vice-captain: Beta")).toHaveAttribute(
      "title",
      "Vice-captain",
    );
    expect(within(squadTable).getByText("Gamma").closest("tr")).toHaveTextContent("Bench");
    expect(within(squadTable).getByRole("columnheader", { name: "Player" })).toHaveClass("sticky");
    expect(within(squadTable).getByRole("columnheader", { name: "GW1 role" })).toBeInTheDocument();
    expect(screen.getByText(/Scroll sideways to see every gameweek/)).toBeInTheDocument();
    expect(within(squadTable).getByRole("columnheader", { name: /Total 3 GWs xP/ })).toBeInTheDocument();
    expect(within(squadTable).getByRole("columnheader", { name: /Total 5 GWs xP/ })).toBeInTheDocument();
    for (let gw = 1; gw <= 5; gw++) {
      expect(within(squadTable).getByRole("columnheader", { name: `GW${gw} xP` })).toBeInTheDocument();
    }
    const plannedXi = within(squadTable).getByRole("row", {
      name: /Planned XI xP \(11\)/,
    });
    const plannedBench = within(squadTable).getByRole("row", {
      name: /Planned bench xP \(4\)/,
    });
    const plannedSquad = within(squadTable).getByRole("row", {
      name: /Planned squad xP \(15\)/,
    });
    expect(within(plannedXi).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "120.9",
      "199.9",
      "41.9",
      "39.5",
      "39.5",
      "39.5",
      "39.5",
    ]);
    expect(within(plannedBench).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "27.0",
      "45.0",
      "9.0highest",
      "9.0",
      "9.0",
      "9.0",
      "9.0",
    ]);
    expect(within(plannedSquad).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "147.9",
      "244.9",
      "50.9",
      "48.5",
      "48.5",
      "48.5",
      "48.5",
    ]);
    expect(
      within(squadTable).getByLabelText(
        "GW1 Planned bench xP (4), highest complete bench xP in loaded horizon: 9.0",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/post-transfer squad: 11 planned starters/)).toHaveTextContent(
      "Sorting the fixed GW1 player rows does not change these totals",
    );
    expect(
      screen.queryByRole("region", { name: "Squad xP and Bench Boost outlook" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/unconditional player forecasts/)).toHaveTextContent(
      "continue after a later planned transfer-out",
    );
    const alphaRow = within(squadTable).getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    const alphaCells = within(alphaRow!).getAllByRole("cell");
    expect(alphaCells[1]).toHaveClass("sticky");
    expect(alphaCells.slice(5).map((cell) => cell.textContent)).toEqual([
      "19.0",
      "30.2",
      "7.4",
      "6.1",
      "5.5",
      "4.9",
      "6.3",
    ]);

    const gw1Sort = within(squadTable).getByRole("button", {
      name: "Sort by player xP for GW1",
    });
    await user.click(gw1Sort);
    expect(gw1Sort.closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(gw1Sort.querySelector('[data-sort-direction="descending"]')).toBeInTheDocument();
    await user.click(gw1Sort);
    expect(gw1Sort.closest("th")).toHaveAttribute("aria-sort", "ascending");
    expect(gw1Sort.querySelector('[data-sort-direction="ascending"]')).toBeInTheDocument();
    const oneGwAscending = within(squadTable)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-player-code"))
      .map((row) => row.getAttribute("data-player-code"));
    expect(oneGwAscending).toHaveLength(15);
    expect(oneGwAscending[0]).toBe("3");
    expect(oneGwAscending.at(-1)).toBe("1");
    // Sorting changes order, but code-keyed role colour/captaincy stays attached to Alpha.
    expect(within(squadTable).getByText("Alpha").closest("tr")).toHaveClass("bg-amber-100/70");
    expect(within(squadTable).getByLabelText("Captain: Alpha")).toBeInTheDocument();

    // Gamma's three-GW total is null because GW2 is unmeasured, so it sorts last both ways.
    const totalThreeSort = within(squadTable).getByRole("button", {
      name: "Sort by total player xP from GW1 through GW3",
    });
    await user.click(totalThreeSort);
    const totalThreeDescending = within(squadTable)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-player-code"))
      .map((row) => row.getAttribute("data-player-code"));
    expect(totalThreeDescending).toHaveLength(15);
    expect(totalThreeDescending[0]).toBe("1");
    expect(totalThreeDescending.at(-1)).toBe("3");
    await user.click(totalThreeSort);
    expect(totalThreeSort.closest("th")).toHaveAttribute("aria-sort", "ascending");
    const totalThreeAscending = within(squadTable)
      .getAllByRole("row")
      .filter((row) => row.hasAttribute("data-player-code"))
      .map((row) => row.getAttribute("data-player-code"));
    expect(totalThreeAscending.at(-1)).toBe("3");

    await user.click(
      within(squadTable).getByRole("button", { name: "Show gameweek details for Alpha" }),
    );
    expect(
      within(squadTable).getByRole("button", { name: "Hide gameweek details for Alpha" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(within(squadTable).getByText("Starting XI · captain")).toBeInTheDocument();
    expect(within(squadTable).getAllByText(/^GW[1-5]$/)).toHaveLength(5);
    expect(within(squadTable).getByText("6.1 xP")).toBeInTheDocument();
    expect(within(squadTable).getAllByText("Not in post-transfer squad")).toHaveLength(4);
    expect(screen.queryByText(/Platform Next GW suggestion/)).not.toBeInTheDocument();
    expect(window.localStorage.getItem("fpl-solved-plan")).toBeNull();
  });

  it("fails visibly instead of rendering a malformed custom squad", async () => {
    const malformedPlan: NextGwPlan = {
      ...customPlan,
      optimizer_run_id: "malformed-custom-run",
      weeks: [
        { ...customPlan.weeks[0], players: customPlan.weeks[0].players.slice(0, 14) },
        ...customPlan.weeks.slice(1),
      ],
    };
    window.location.hash = "#plan-builder?run=" + malformedPlan.optimizer_run_id;
    vi.mocked(loadNextGw).mockResolvedValue({ plans: [malformedPlan] });

    render(<PlanBuilderPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The exact custom plan failed the GW1 squad contract",
    );
    expect(
      screen.queryByRole("table", { name: "GW1 custom squad analysis" }),
    ).not.toBeInTheDocument();
  });

  it("shows honest staged progress while the local optimizer is running", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: readyRuntime,
    });
    let reportStage: ((stage: string | null) => void) | undefined;
    let resolvePlan!: (summary: Awaited<ReturnType<typeof solvePlan>>) => void;
    vi.mocked(solvePlan).mockImplementation((_request, onStage) => {
      reportStage = onStage;
      return new Promise((resolve) => {
        resolvePlan = resolve;
      });
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(await screen.findByText("plan server online")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Solve now with my rules" }));

    const progress = await screen.findByRole("status");
    expect(screen.getByLabelText("Solve")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Unlock Alpha" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Back to rules" })).toBeDisabled();
    expect(progress).toHaveTextContent("Preparing your optimization");
    expect(progress).toHaveTextContent("cannot provide a trustworthy completion percentage");
    expect(screen.getByRole("button", { name: "Solving…" })).toBeDisabled();

    await act(async () => {
      reportStage?.("solving squad (exact ILP + bounded transfer search)");
    });
    expect(progress).toHaveTextContent("Searching for your best legal squad");
    expect(progress).toHaveTextContent("usually the longest step");

    await act(async () => {
      reportStage?.("publishing BI export and dashboard read models");
    });
    expect(progress).toHaveTextContent("Publishing your exact plan");
    expect(progress).toHaveTextContent("validating its provenance");

    // A final null status poll must not regress the visible stage back to "preparing".
    await act(async () => {
      reportStage?.(null);
    });
    expect(progress).toHaveTextContent("Publishing your exact plan");

    await act(async () => {
      resolvePlan({
        optimizer_run_id: "progress-run",
        decision_sha256: "deadbeef",
        gw: 1,
        gw_expected_points: 60,
        horizon_expected_points: 300,
        hit_points: 0,
        squad_cost_tenths: 990,
        captain: "Alpha",
        vice_captain: "Beta",
      });
    });
    expect(
      await screen.findByText("Your solved plan is not in the published read model"),
    ).toBeInTheDocument();
  });

  it("opens an explicitly entered manual run id after publishing", async () => {
    const user = userEvent.setup();
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], customPlan, plans[1]],
    });
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    const command = document.querySelector("pre")?.textContent ?? "";
    expect(command).toMatch(/plan_my_rules_[a-z0-9]+\.json/i);
    expect(screen.getByText(/primary button sends these rules/)).toHaveTextContent(
      "transparent manual fallback",
    );
    expect(screen.getByText(/unique output/)).toHaveTextContent(
      command.match(/D:\\tmp\\gw1\\dev-latest\\plan_my_rules_[a-z0-9]+\.json/i)?.[0] ?? "",
    );

    await user.type(
      screen.getByRole("textbox", { name: "Published optimizer run id" }),
      customPlan.optimizer_run_id,
    );
    await user.click(screen.getByRole("button", { name: "Open exact custom plan" }));

    expect(await screen.findByText("Your plan — GW1")).toBeInTheDocument();
    expect(window.location.hash).toBe("#plan-builder?run=solved-custom-run");
    expect(window.localStorage.getItem("fpl-solved-plan")).toBe("solved-custom-run");
    expect(reloadPublishedReadModels).toHaveBeenCalledTimes(1);
  });

  it("fails visibly when the exact custom run is absent instead of showing a different squad", async () => {
    window.localStorage.setItem("fpl-solved-plan", "missing-custom-run");

    render(<PlanBuilderPage />);

    expect(
      await screen.findByText("Your solved plan is not in the published read model"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("missing-custom-run");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "will not silently show the platform squad",
    );
    expect(screen.getByRole("link", { name: "View platform suggestion" })).toHaveAttribute(
      "href",
      "#next-gw",
    );
  });

  it("solves through the local server with locks and exclusions, then stays in Plan Builder", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    const search = screen.getByRole("textbox", { name: "Search player" });
    await user.type(search, "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await user.click(screen.getByRole("radio", { name: "Exclude" }));
    await user.clear(search);
    await user.type(search, "Beta");
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    await user.click(screen.getByText("25%"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    // offline by default: the solve button is disabled and the start command is the fallback
    expect(await screen.findByText(/plan server online|Offline — start it/)).toBeInTheDocument();
    expect(screen.getByText(/Offline — start it/)).toBeInTheDocument();
    expect(screen.getByText(".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server")).toBeInTheDocument();
    const solve = screen.getByRole("button", { name: /Solve now with my rules/ });
    expect(solve).toBeDisabled();
    // coming online enables it; solving posts the exact rules and hands off to Next GW
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: readyRuntime,
    });
    await user.click(screen.getByRole("button", { name: /Re-check/ }));
    expect(await screen.findByText("plan server online")).toBeInTheDocument();
    vi.mocked(solvePlan).mockResolvedValue({
      optimizer_run_id: "solved-run-1",
      decision_sha256: "deadbeef",
      gw: 1,
      gw_expected_points: 60.7,
      horizon_expected_points: 317.2,
      hit_points: 0,
      squad_cost_tenths: 995,
      captain: "Gibbs-White",
      vice_captain: "O'Reilly",
    });
    expect(solve).toBeEnabled();
    await user.click(solve);
    await waitFor(() => expect(vi.mocked(solvePlan)).toHaveBeenCalledTimes(1));
    expect(vi.mocked(solvePlan)).toHaveBeenCalledWith(
      { locks: [1], excludes: [2], minBenchAppearance: 0.25 },
      expect.any(Function),
      "",
    );
    await waitFor(() => expect(window.localStorage.getItem("fpl-solved-plan")).toBe("solved-run-1"));
    expect(window.localStorage.getItem("fpl-plan-request")).toBeNull(); // applied, not pending
    expect(window.location.hash).toBe("#plan-builder?run=solved-run-1");
    expect(reloadPublishedReadModels).toHaveBeenCalledTimes(1);
    // jsdom cannot perform the real full-page reload, so the current stale export must show
    // the exact-run-missing error rather than fall back to one of the formal plans.
    expect(
      await screen.findByText("Your solved plan is not in the published read model"),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("solved-run-1");
  });

  it("does not enable solve when HTTP status succeeds but the solver runtime is unready", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: {
        ...readyRuntime,
        pulp_package_version: null,
        cbc_binary_version: null,
        solver_ready: false,
      },
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("solver runtime unavailable")).toBeInTheDocument();
    expect(screen.queryByText("plan server online")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve now with my rules" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-check" })).toBeEnabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      ".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server",
    );
    expect(solvePlan).not.toHaveBeenCalled();
  });

  it("requires restart when an older status response omits the runtime handshake", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("solver runtime unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve now with my rules" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      ".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server",
    );
  });

  it("blocks solve when the server reports a dirty worktree", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: false,
      forecast_ready: true,
      runtime: readyRuntime,
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("commit required")).toBeInTheDocument();
    expect(screen.queryByText("plan server online")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve now with my rules" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Commit them, then re-check",
    );
  });

  it("blocks solve when the server reports the forecast is missing", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: false,
      runtime: readyRuntime,
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("forecast unavailable")).toBeInTheDocument();
    expect(screen.queryByText("plan server online")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve now with my rules" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Regenerate it using the exact development workflow in dashboard/README.md",
    );
  });

  it("does not turn a successful solve into an error when localStorage rejects writes", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: readyRuntime,
    });
    vi.mocked(solvePlan).mockResolvedValue({
      optimizer_run_id: "storage-safe-run",
      decision_sha256: "feedface",
      gw: 1,
      gw_expected_points: 60,
      horizon_expected_points: 300,
      hit_points: 0,
      squad_cost_tenths: 990,
      captain: "Alpha",
      vice_captain: "Beta",
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(await screen.findByText("plan server online")).toBeInTheDocument();

    const storage = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("storage denied", "SecurityError");
      });
    await user.click(screen.getByRole("button", { name: "Solve now with my rules" }));

    expect(
      await screen.findByText("Your solved plan is not in the published read model"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Browser storage is unavailable/)).toBeInTheDocument();
    expect(window.location.hash).toBe("#plan-builder?run=storage-safe-run");
    expect(screen.queryByText(/storage denied/)).not.toBeInTheDocument();
    expect(reloadPublishedReadModels).toHaveBeenCalledTimes(1);
    storage.mockRestore();
  });

  it("uses a fragment token for LAN status and solve calls without putting it in an HTTP query", async () => {
    const user = userEvent.setup();
    window.location.hash = "#plan-builder?server_token=lan-secret";
    vi.mocked(fetchPlanStatus).mockResolvedValue({
      busy: false,
      stage: null,
      last_error: null,
      last_result: null,
      worktree_clean: true,
      forecast_ready: true,
      runtime: readyRuntime,
    });
    vi.mocked(solvePlan).mockResolvedValue({
      optimizer_run_id: "lan-solved-run",
      decision_sha256: "cafe",
      gw: 1,
      gw_expected_points: 60,
      horizon_expected_points: 300,
      hit_points: 0,
      squad_cost_tenths: 990,
      captain: "Alpha",
      vice_captain: "Beta",
    });

    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));

    expect(await screen.findByText("plan server online")).toBeInTheDocument();
    expect(screen.getByLabelText(/Plan server token/)).toHaveValue("lan-secret");
    expect(fetchPlanStatus).toHaveBeenCalledWith("lan-secret");
    await user.click(screen.getByRole("button", { name: "Solve now with my rules" }));
    await waitFor(() =>
      expect(solvePlan).toHaveBeenCalledWith(
        { locks: [], excludes: [], minBenchAppearance: null },
        expect.any(Function),
        "lan-secret",
      ),
    );
    expect(window.location.hash).toBe(
      "#plan-builder?run=lan-solved-run&server_token=lan-secret",
    );
    expect(reloadPublishedReadModels).toHaveBeenCalledTimes(1);
  });
});
