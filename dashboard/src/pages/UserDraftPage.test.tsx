import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import auditSample from "@/data/sampleOptimizerAudit.json";
import nextGwSample from "@/data/sampleNextGw.json";
import playersSample from "@/data/samplePlayers.json";
import type {
  NextGwPlan,
  OptimizerAuditData,
  PlayerFixture,
  PlayerRecord,
  PlanPlayer,
} from "@/data/types";
import {
  fetchManagerTeamMembers,
  fetchManagerTeamMembersCapture,
  type ManagerTeamPreview,
} from "@/lib/planServer";
import { USER_DRAFT_STORAGE_KEY, UserDraftPage } from "./UserDraftPage";

vi.mock("@/data/load", () => ({
  loadNextGw: vi.fn(),
  loadOptimizerAudit: vi.fn(),
  loadPlayers: vi.fn(),
}));
vi.mock("@/lib/planServer", () => ({
  fetchManagerTeamMembers: vi.fn(),
  fetchManagerTeamMembersCapture: vi.fn(),
}));

const plans = nextGwSample.plans as unknown as NextGwPlan[];
const audit = auditSample as unknown as OptimizerAuditData;
const basePlayer = playersSample.players[0] as unknown as PlayerRecord;
const baseFixture = basePlayer.fixtures[0] as PlayerFixture;
const positions = [
  "GK",
  "GK",
  ...Array(5).fill("DEF"),
  ...Array(5).fill("MID"),
  ...Array(3).fill("FWD"),
] as string[];

function draftPlayer(index: number): PlayerRecord {
  const code = index + 1;
  return {
    ...basePlayer,
    run_id: plans[0].forecast_run_id,
    season: plans[0].season,
    code,
    web_name: `Draft ${String(code).padStart(2, "0")}`,
    position: positions[index],
    team_code: 100 + code,
    team_short_name: `T${code}`,
    now_cost: 80,
    fixtures: Array.from({ length: 5 }, (_, gwIndex) => ({
      ...baseFixture,
      gw: gwIndex + 1,
      fixture: code * 100 + gwIndex + 1,
      opponent_team_code: 900 + gwIndex,
      opponent_short_name: `O${gwIndex + 1}`,
      expected_points: 1,
    })),
  };
}

const draftPlayers = positions.map((_, index) => draftPlayer(index));

const managerPreview: ManagerTeamPreview = {
  capture_id: "capture-1",
  captured_at: "2026-08-23T10:00:00Z",
  manager_id: 123456,
  entry_name: "Manager Test XI",
  picks_event: plans[0].gw_from,
  planning_gw: plans[0].gw_from,
  bank_tenths: 5,
  squad_selling_value_tenths: 750,
  free_transfers_available: 1,
  free_transfers_source: "derived from captured transfers",
  existing_hit_points: 0,
  players: draftPlayers.map((player, index) => ({
    element_id: index + 1,
    code: player.code,
    web_name: player.web_name,
    position: player.position as "GK" | "DEF" | "MID" | "FWD",
    team_id: index + 1,
    team_code: player.team_code,
    now_cost: player.now_cost ?? 0,
    purchase_price: 50,
    selling_price: 50,
  })),
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  window.localStorage.clear();
  window.location.hash = "#squad-draft";
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  vi.mocked(loadPlayers).mockResolvedValue({ players: draftPlayers, manifest: null });
  vi.mocked(fetchManagerTeamMembers).mockReset();
  vi.mocked(fetchManagerTeamMembersCapture).mockReset();
});

describe("UserDraftPage", () => {
  it("keeps hosted Squad Draft manual and never exposes manager import controls", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");

    render(<UserDraftPage />);

    expect(await screen.findByRole("heading", { name: "Squad Draft" })).toBeInTheDocument();
    expect(screen.getByText(/Current-team import is intentionally local-only/)).toBeInTheDocument();
    expect(screen.queryByLabelText("FPL manager ID")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Plan server token/)).not.toBeInTheDocument();
    expect(fetchManagerTeamMembers).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Add Draft 01" })).toBeEnabled();
  });

  it("blocks captured-manager handoffs on hosted builds without probing a Plan Server", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    window.location.hash =
      `#squad-draft?optimizer_run_id=${encodeURIComponent(plans[0].optimizer_run_id)}` +
      "&source=manager_current&manager_capture_id=capture-1";

    render(<UserDraftPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /require the trusted local Plan Server/i,
    );
    expect(fetchManagerTeamMembersCapture).not.toHaveBeenCalled();
  });

  it("allows an over-budget legal 15 and keeps cost/xP totals in the final row", async () => {
    const user = userEvent.setup();
    const { container } = render(<UserDraftPage />);
    await screen.findByRole("heading", { name: "Squad Draft" });

    for (const emptyGroup of [
      "Goalkeepers (0/2)",
      "Defenders (0/5)",
      "Midfielders (0/5)",
      "Forwards (0/3)",
    ]) {
      expect(screen.getByRole("rowgroup", { name: emptyGroup })).toBeInTheDocument();
    }

    for (const player of draftPlayers) {
      await user.click(screen.getByRole("button", { name: `Add ${player.web_name}` }));
    }

    expect(screen.getByText("15/15 players")).toBeInTheDocument();
    expect(screen.getByText(/above the recorded/)).toHaveTextContent(
      "\u00a3120.0m",
    );
    const footer = container.querySelector("tfoot");
    expect(footer).not.toBeNull();
    expect(within(footer!).getByText("Draft squad total (15/15)")).toBeInTheDocument();
    const footerText = footer!.textContent ?? "";
    expect(footerText).toContain("\u00a3120.0m");
    expect(footerText).toContain("45.0");
    expect(footerText).toContain("75.0");
    expect(footerText.match(/15\.0/g)).toHaveLength(5);

    const groupExpectations = [
      { label: "Goalkeepers (2/2)", position: "GK", codes: [1, 2] },
      { label: "Defenders (5/5)", position: "DEF", codes: [3, 4, 5, 6, 7] },
      { label: "Midfielders (5/5)", position: "MID", codes: [8, 9, 10, 11, 12] },
      { label: "Forwards (3/3)", position: "FWD", codes: [13, 14, 15] },
    ];
    const groupedBodies = groupExpectations.map(({ label, position, codes }) => {
      const body = screen.getByRole("rowgroup", { name: label });
      const sectionHead = body.querySelector('th[scope="rowgroup"]');
      expect(sectionHead).toHaveTextContent(label);
      const playerRows = [...body.querySelectorAll<HTMLElement>("tr[data-player-code]")];
      expect(playerRows.map((row) => Number(row.dataset.playerCode))).toEqual(codes);
      expect(playerRows.every((row) => row.dataset.position === position)).toBe(true);
      return body;
    });
    expect(groupedBodies.map((body) => body.getAttribute("aria-label"))).toEqual(
      groupExpectations.map(({ label }) => label),
    );

    const footerBeforeSort = footer!.textContent;
    await user.click(screen.getByRole("button", { name: "Sort by Player" }));
    await user.click(screen.getByRole("button", { name: "Sort by Player" }));
    expect(screen.getByRole("columnheader", { name: /Player/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(
      [...screen.getByRole("rowgroup", { name: "Goalkeepers (2/2)" })
        .querySelectorAll<HTMLElement>("tr[data-player-code]")]
        .map((row) => Number(row.dataset.playerCode)),
    ).toEqual([2, 1]);
    expect(container.querySelector("tfoot")?.textContent).toBe(footerBeforeSort);

    expect(screen.getByText(/Highest measured bench after choosing the best legal XI/))
      .toHaveTextContent("GW1");
    expect(screen.getByText(/This is only a Triple Captain shortlist signal/))
      .toBeInTheDocument();

    const saved = JSON.parse(
      window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}",
    ) as { playerCodes?: number[] };
    expect(saved.playerCodes).toEqual(draftPlayers.map((player) => player.code));
  });

  it("restores the exact-vintage draft and lets Selected remove the player", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      USER_DRAFT_STORAGE_KEY,
      JSON.stringify({
        version: 2,
        optimizerRunId: plans[0].optimizer_run_id,
        forecastRunId: plans[0].forecast_run_id,
        season: plans[0].season,
        playerCodes: [1],
      }),
    );
    const { container } = render(<UserDraftPage />);
    await screen.findByText("1/15 players");

    expect(container.querySelector("tfoot")?.textContent).toContain(
      "Draft squad total (1/15)",
    );
    expect(screen.getByRole("rowgroup", { name: "Goalkeepers (1/2)" })).toBeInTheDocument();
    expect(screen.getByRole("rowgroup", { name: "Defenders (0/5)" })).toBeInTheDocument();
    expect(screen.getByRole("rowgroup", { name: "Midfielders (0/5)" })).toBeInTheDocument();
    expect(screen.getByRole("rowgroup", { name: "Forwards (0/3)" })).toBeInTheDocument();
    const selectedButton = screen.getByRole("button", {
      name: "Remove Draft 01 from draft",
    });
    expect(selectedButton).toBeEnabled();
    expect(selectedButton).toHaveAttribute("aria-pressed", "true");

    await user.click(selectedButton);
    expect(await screen.findByText("0/15 players")).toBeInTheDocument();
    expect(screen.getByRole("rowgroup", { name: "Goalkeepers (0/2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Draft 01" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({
      version: 3,
      seedSource: "manual",
      playerCodes: [],
    });
    expect(window.localStorage.getItem("fpl-solved-plan")).toBeNull();
  });

  it("replaces the draft with the exact optimized squad from an explicit handoff", async () => {
    const planPlayers: PlanPlayer[] = draftPlayers.map((player, index) => {
      const isBenchGoalkeeper = index === 1;
      const isBenchOutfield = index === 11 || index === 13 || index === 14;
      return {
        code: player.code,
        web_name: player.web_name,
        position: player.position,
        team_code: player.team_code,
        team_short_name: player.team_short_name,
        now_cost: player.now_cost,
        role: isBenchGoalkeeper
          ? "bench_goalkeeper"
          : isBenchOutfield
            ? "bench_outfield"
            : "starting_xi",
        bench_order_index: isBenchGoalkeeper ? 0 : isBenchOutfield ? index : null,
        is_captain: index === 0,
        is_vice_captain: index === 2,
        transferred_in: false,
        transferred_out: false,
        expected_points: 1,
      };
    });
    const handoffPlan: NextGwPlan = {
      ...plans[0],
      optimizer_run_id: "custom-handoff",
      decision_sha256: "custom-handoff-decision",
      plan_kind: "user_custom",
      display_label: "Your optimized handoff",
      weeks: [
        { ...plans[0].weeks[0], players: planPlayers },
        ...plans[0].weeks.slice(1),
      ],
    };
    const handoffAudit = {
      ...audit.plans[0],
      optimizer_run_id: handoffPlan.optimizer_run_id,
      decision_sha256: handoffPlan.decision_sha256,
      forecast_run_id: handoffPlan.forecast_run_id,
      plan_kind: handoffPlan.plan_kind,
      display_label: handoffPlan.display_label,
      as_of: handoffPlan.as_of,
      season: handoffPlan.season,
      gw_from: handoffPlan.gw_from,
      gw_to: handoffPlan.gw_to,
    };
    vi.mocked(loadNextGw).mockResolvedValue({ plans: [...plans, handoffPlan] });
    vi.mocked(loadOptimizerAudit).mockResolvedValue({
      ...audit,
      plans: [...audit.plans, handoffAudit],
    });
    window.localStorage.setItem(
      USER_DRAFT_STORAGE_KEY,
      JSON.stringify({
        version: 2,
        optimizerRunId: plans[0].optimizer_run_id,
        forecastRunId: plans[0].forecast_run_id,
        season: plans[0].season,
        playerCodes: [1],
      }),
    );
    window.location.hash = "#squad-draft?optimizer_run_id=custom-handoff";

    const { container } = render(<UserDraftPage />);

    expect(await screen.findByText("15/15 players")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Forwarded 15 optimized players from Your optimized handoff",
    );
    expect(container.querySelectorAll("tr[data-player-code]")).toHaveLength(15);
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({
      version: 3,
      seedSource: "optimized",
      managerCaptureId: null,
      optimizerRunId: handoffPlan.optimizer_run_id,
      forecastRunId: handoffPlan.forecast_run_id,
      playerCodes: draftPlayers.map((player) => player.code),
    });
    expect(window.location.hash).toBe("#squad-draft");
  });

  it("loads the exact captured current team from a typed handoff", async () => {
    vi.mocked(fetchManagerTeamMembersCapture).mockResolvedValue(managerPreview);
    window.location.hash =
      `#squad-draft?optimizer_run_id=${encodeURIComponent(plans[0].optimizer_run_id)}` +
      "&source=manager_current&manager_capture_id=capture-1";

    const { container } = render(<UserDraftPage />);

    expect(await screen.findByText("15/15 players")).toBeInTheDocument();
    expect(fetchManagerTeamMembersCapture).toHaveBeenCalledWith("capture-1", "");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Forwarded 15 players from Manager Test XI's captured current team",
    );
    expect(container.querySelectorAll("tr[data-player-code]")).toHaveLength(15);
    expect(screen.getByLabelText("Imported manager values")).toHaveTextContent(
      "Current selling value",
    );
    expect(screen.getByLabelText("Imported manager values")).toHaveTextContent(
      "£75.0m",
    );
    expect(screen.getByLabelText("Imported manager values")).toHaveTextContent(
      "Bank£0.5m",
    );
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({
      version: 3,
      seedSource: "manager_current",
      managerCaptureId: "capture-1",
      optimizerRunId: plans[0].optimizer_run_id,
      forecastRunId: plans[0].forecast_run_id,
      season: plans[0].season,
      playerCodes: draftPlayers.map((player) => player.code),
    });
    expect(window.location.hash).toBe("#squad-draft");
  });

  it("atomically replaces the draft through the direct Manager ID shortcut", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      USER_DRAFT_STORAGE_KEY,
      JSON.stringify({
        version: 3,
        seedSource: "manual",
        optimizerRunId: plans[0].optimizer_run_id,
        forecastRunId: plans[0].forecast_run_id,
        season: plans[0].season,
        managerCaptureId: null,
        playerCodes: [1],
      }),
    );
    vi.mocked(fetchManagerTeamMembers).mockResolvedValue(managerPreview);
    render(<UserDraftPage />);
    await screen.findByText("1/15 players");

    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Fetch current team" }));

    expect(await screen.findByText("15/15 players")).toBeInTheDocument();
    expect(fetchManagerTeamMembers).toHaveBeenCalledWith("123456", "");
    expect(screen.getByText(/does not optimize transfers/i)).toBeInTheDocument();
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toMatchObject({
      version: 3,
      seedSource: "manager_current",
      managerCaptureId: "capture-1",
      playerCodes: draftPlayers.map((player) => player.code),
    });
  });

  it("accepts and explicitly remembers a LAN token for the direct shortcut", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchManagerTeamMembers).mockResolvedValue(managerPreview);
    render(<UserDraftPage />);
    await screen.findByText("0/15 players");

    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.type(screen.getByLabelText(/Plan server token/), "lan-secret");
    await user.click(
      screen.getByRole("button", { name: "Remember token on this browser" }),
    );
    await user.click(screen.getByRole("button", { name: "Fetch current team" }));

    expect(fetchManagerTeamMembers).toHaveBeenCalledWith("123456", "lan-secret");
    expect(window.localStorage.getItem("fpl-plan-server-token")).toBe("lan-secret");
    expect(await screen.findByText("15/15 players")).toBeInTheDocument();
  });

  it("explains invalid IDs and freezes draft mutations while an import is pending", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      USER_DRAFT_STORAGE_KEY,
      JSON.stringify({
        version: 3,
        seedSource: "manual",
        optimizerRunId: plans[0].optimizer_run_id,
        forecastRunId: plans[0].forecast_run_id,
        season: plans[0].season,
        managerCaptureId: null,
        playerCodes: [1],
      }),
    );
    let resolveImport: ((preview: ManagerTeamPreview) => void) | null = null;
    vi.mocked(fetchManagerTeamMembers).mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }),
    );
    render(<UserDraftPage />);
    await screen.findByText("1/15 players");

    const managerId = screen.getByLabelText("FPL manager ID");
    await user.type(managerId, "0");
    expect(screen.getByText(/value greater than zero/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fetch current team" })).toBeDisabled();
    await user.clear(managerId);
    await user.type(managerId, "123456");
    await user.click(screen.getByRole("button", { name: "Fetch current team" }));

    expect(managerId).toBeDisabled();
    expect(screen.getByLabelText(/Plan server token/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Draft 01" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove Draft 01 from draft" })).toBeDisabled();

    await act(async () => {
      resolveImport?.(managerPreview);
      await Promise.resolve();
    });
    expect(await screen.findByText("15/15 players")).toBeInTheDocument();
    expect(managerId).toBeEnabled();
  });

  it("preserves the existing draft when direct manager import fails", async () => {
    const user = userEvent.setup();
    const stored = {
      version: 3,
      seedSource: "manual",
      optimizerRunId: plans[0].optimizer_run_id,
      forecastRunId: plans[0].forecast_run_id,
      season: plans[0].season,
      managerCaptureId: null,
      playerCodes: [1],
    };
    window.localStorage.setItem(USER_DRAFT_STORAGE_KEY, JSON.stringify(stored));
    vi.mocked(fetchManagerTeamMembers).mockRejectedValue(new Error("manager not found"));
    render(<UserDraftPage />);
    await screen.findByText("1/15 players");

    await user.type(screen.getByLabelText("FPL manager ID"), "999999");
    await user.click(screen.getByRole("button", { name: "Fetch current team" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "manager not found Your existing draft was kept unchanged",
    );
    expect(screen.getByText("1/15 players")).toBeInTheDocument();
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toEqual(stored);
  });

  it("rejects an owned-player price mismatch without replacing the draft", async () => {
    const user = userEvent.setup();
    const stored = {
      version: 3,
      seedSource: "manual",
      optimizerRunId: plans[0].optimizer_run_id,
      forecastRunId: plans[0].forecast_run_id,
      season: plans[0].season,
      managerCaptureId: null,
      playerCodes: [1],
    };
    window.localStorage.setItem(USER_DRAFT_STORAGE_KEY, JSON.stringify(stored));
    vi.mocked(fetchManagerTeamMembers).mockResolvedValue({
      ...managerPreview,
      players: managerPreview.players.map((player, index) =>
        index === 0 ? { ...player, now_cost: player.now_cost + 1 } : player,
      ),
    });
    render(<UserDraftPage />);
    await screen.findByText("1/15 players");

    await user.type(screen.getByLabelText("FPL manager ID"), "123456");
    await user.click(screen.getByRole("button", { name: "Fetch current team" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not match the selected forecast roster",
    );
    expect(screen.getByText("1/15 players")).toBeInTheDocument();
    expect(
      JSON.parse(window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}"),
    ).toEqual(stored);
  });

  it("fails closed when the platform plan has no exact audit rules snapshot", async () => {
    vi.mocked(loadOptimizerAudit).mockResolvedValue({ plans: [] });
    render(<UserDraftPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /cannot find one exact rules snapshot/i,
    );
    await waitFor(() => expect(loadPlayers).toHaveBeenCalledOnce());
  });
});
