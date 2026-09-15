import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { loadCompetitiveSchedule } from "@/data/competitiveSchedule";
import type { TeamRecord } from "@/data/types";
import { cups, schedule } from "@/data/competitiveSchedule.fixture";
import { CompetitiveFixtureCalendar } from "./CompetitiveFixtureCalendar";

vi.mock("@/data/competitiveSchedule", () => ({loadCompetitiveSchedule: vi.fn()}));
const teams = [{run_id: "unchanged", as_of: "2026-09-14T00:00:00Z", season: "2026-27",
  team_code: 3, team_name: "Arsenal", short_name: "ARS", form: null, fixtures: []}] as TeamRecord[];

describe("club calendar interactions", () => {
  beforeEach(() => { vi.mocked(loadCompetitiveSchedule).mockResolvedValue(cups); });
  it("shows league difficulty, keeps cup grey, and supports a reversible empty range", async () => {
    const user = userEvent.setup();
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    const cup = await screen.findByRole("button", {name: /Arsenal: CUP/});
    expect(cup.className).toContain("bg-slate-200");
    expect(cup.textContent).toContain("LC");
    expect(screen.getByText("DGW · 2 fixtures")).toBeVisible();
    await user.click(screen.getByRole("radio", {name: "Official FDR"}));
    expect(screen.getByRole("button", {name: /Arsenal: BHA/}).className).toContain("red");
    expect(cup.className).toContain("bg-slate-200");
    await user.clear(screen.getByLabelText("Calendar from"));
    await user.type(screen.getByLabelText("Calendar from"), "2027-01-01");
    expect(screen.getByRole("alert")).toHaveTextContent("end date");
    await user.click(screen.getByRole("button", {name: "Reset calendar"}));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
  });
  it("a missing sidecar leaves PL visible and discloses unknown cup coverage", async () => {
    vi.mocked(loadCompetitiveSchedule).mockRejectedValue(new Error("HTTP 404"));
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("cup workload is unknown"));
    expect(screen.getByRole("button", {name: /Arsenal: BHA/})).toBeVisible();
  });
  it("keeps a BGW column when the only selected club is blank", async () => {
    const user = userEvent.setup();
    const extra = {...teams[0], team_code: 36, team_name: "Brighton", short_name: "BHA"};
    const withBlank = {...schedule, teams: [...schedule.teams, {...schedule.teams[0], team_code: 36, fixtures: []}]};
    render(<CompetitiveFixtureCalendar teams={[...teams, extra]} schedule={withBlank} fromGw={5} toGw={5} />);
    await screen.findByRole("button", {name: /Arsenal: CUP/});
    await user.click(screen.getByRole("button", {name: "Calendar teams: All teams"}));
    await user.click(screen.getByRole("checkbox", {name: "Brighton"}));
    await user.keyboard("{Escape}");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("GW5")).toBeVisible();
    expect(within(table).getByText("BGW")).toBeVisible();
    expect(within(table).queryByText("Midweek")).not.toBeInTheDocument();
  });
});
