import { render, screen, waitFor, within } from "@testing-library/react";
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
import { USER_DRAFT_STORAGE_KEY, UserDraftPage } from "./UserDraftPage";

vi.mock("@/data/load", () => ({
  loadNextGw: vi.fn(),
  loadOptimizerAudit: vi.fn(),
  loadPlayers: vi.fn(),
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

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.location.hash = "#squad-draft";
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  vi.mocked(loadPlayers).mockResolvedValue({ players: draftPlayers, manifest: null });
});

describe("UserDraftPage", () => {
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
    ).toMatchObject({ playerCodes: [] });
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
      version: 2,
      optimizerRunId: handoffPlan.optimizer_run_id,
      forecastRunId: handoffPlan.forecast_run_id,
      playerCodes: draftPlayers.map((player) => player.code),
    });
    expect(window.location.hash).toBe("#squad-draft");
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
