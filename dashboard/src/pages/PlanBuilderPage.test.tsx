// Plan builder (wizard v2): custom rules and their exact result stay here. The shared player
// picker supports mutually-exclusive green locks and red exclusions; Next GW remains the
// platform-owned recommendation and is never replaced by a custom solve.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import { fetchPlanStatus, solvePlan } from "@/lib/planServer";
import { reloadPublishedReadModels } from "@/lib/readModelReload";
import playersSample from "@/data/samplePlayers.json";
import nextGwSample from "@/data/sampleNextGw.json";
import auditSample from "@/data/sampleOptimizerAudit.json";
import type { NextGwPlan, OptimizerAuditData, PlayerRecord } from "@/data/types";
import { PlanBuilderPage } from "./PlanBuilderPage";

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadNextGw: vi.fn(),
  loadOptimizerAudit: vi.fn(),
}));

vi.mock("@/lib/planServer", () => ({
  PLAN_SERVER_START_COMMAND: ".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server",
  fetchPlanStatus: vi.fn(),
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
};

const readyRuntime = {
  python_executable: "D:\\repo\\.venv\\Scripts\\python.exe",
  python_prefix: "D:\\repo\\.venv",
  pulp_package_version: "3.3.0",
  cbc_binary_version: "2.10.3",
  solver_ready: true,
} as const;

beforeEach(() => {
  vi.mocked(loadPlayers).mockResolvedValue({ players: builderPlayers, manifest: null });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  vi.mocked(fetchPlanStatus).mockResolvedValue(null); // offline unless a test says otherwise
  vi.mocked(solvePlan).mockReset();
  vi.mocked(reloadPublishedReadModels).mockReset();
  window.localStorage.clear();
  window.location.hash = "";
});

describe("PlanBuilderPage", () => {
  it("starts with the two entry cards; import is clickable and labelled post-deadline", async () => {
    render(<PlanBuilderPage />);
    expect(await screen.findByText("Import my team")).toBeInTheDocument();
    expect(screen.getByText(/Lands after the GW1 deadline/)).toBeInTheDocument();
    expect(screen.getByText("Build from scratch →")).toBeInTheDocument();
  });

  it("opens the import screen, validates the manager id, and offers the scratch fallback", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Import my team"));
    const input = await screen.findByLabelText("FPL manager id");
    await user.type(input, "12a4");
    expect(screen.getByText(/Digits only/)).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "1234567");
    expect(screen.getByText(/Manager #1234567 saved/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Continue to player rules/ }));
    expect(screen.getByLabelText("Search player")).toBeInTheDocument();
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
  });

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
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Paged Player 60/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous players" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next players" }));

    expect(screen.getByText(/Players 51–76 of 76/)).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next players" })).toBeDisabled();
    const laterPlayer = screen.getByRole("button", { name: /Paged Player 60/ });
    await user.click(laterPlayer);
    expect(laterPlayer).toHaveAttribute("aria-pressed", "true");
    expect(laterPlayer).toHaveTextContent("locked");
    expect(laterPlayer.className).toContain("emerald");

    // Searching from a later page resets to the first matching page. The off-page selection
    // remains durable and reaches the v2 optimizer request.
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Alpha");
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
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
    window.location.hash = "#plan-builder?run=" + customPlan.optimizer_run_id;
    vi.mocked(loadNextGw).mockResolvedValue({
      plans: [plans[0], customPlan, plans[1]],
    });

    render(<PlanBuilderPage />);

    expect(await screen.findByText("Your plan — GW1")).toBeInTheDocument();
    expect(screen.getByText("1 locked")).toBeInTheDocument();
    expect(screen.getByText("1 excluded")).toBeInTheDocument();
    expect(screen.getByText(/locked ·/).parentElement).toHaveTextContent("Alpha");
    expect(screen.getByText(/excluded ·/).parentElement).toHaveTextContent("Beta");
    expect(screen.getByText(/optimizer run solved-custo/)).toBeInTheDocument();
    expect(screen.queryByText(/Platform Next GW suggestion/)).not.toBeInTheDocument();
    expect(window.localStorage.getItem("fpl-solved-plan")).toBeNull();
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
