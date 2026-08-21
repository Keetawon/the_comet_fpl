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
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  vi.mocked(loadPlayers).mockResolvedValue({ players: draftPlayers, manifest: null });
});

describe("UserDraftPage", () => {
  it("allows an over-budget legal 15 and keeps cost/xP totals in the final row", async () => {
    const user = userEvent.setup();
    const { container } = render(<UserDraftPage />);
    await screen.findByRole("heading", { name: "Squad Draft" });

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

    expect(screen.getByText(/Highest measured bench after choosing the best legal XI/))
      .toHaveTextContent("GW1");
    expect(screen.getByText(/This is only a Triple Captain shortlist signal/))
      .toBeInTheDocument();

    const saved = JSON.parse(
      window.localStorage.getItem(USER_DRAFT_STORAGE_KEY) ?? "{}",
    ) as { playerCodes?: number[] };
    expect(saved.playerCodes).toEqual(draftPlayers.map((player) => player.code));
  });

  it("restores only the separate exact-vintage browser draft", async () => {
    window.localStorage.setItem(
      USER_DRAFT_STORAGE_KEY,
      JSON.stringify({
        version: 1,
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
    expect(screen.getByRole("button", { name: "Draft 01: Already selected" }))
      .toBeDisabled();
    expect(window.localStorage.getItem("fpl-solved-plan")).toBeNull();
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
