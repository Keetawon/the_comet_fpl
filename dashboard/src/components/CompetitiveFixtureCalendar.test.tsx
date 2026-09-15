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
  it("switches Weekly/Daily without changing fixtures and exports daily dates and listed gaps", async () => {
    const user = userEvent.setup();
    const before = JSON.stringify([schedule, cups]);
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    await screen.findByRole("button", {name: /Arsenal: CUP/});
    await user.click(screen.getByRole("radio", {name: "Daily"}));
    const table = screen.getByRole("table", {name: "All competitions by day"});
    expect(within(table).getAllByRole("columnheader")).toHaveLength(9);
    expect(screen.getByRole("button", {name: /Arsenal: BHA/})).toHaveTextContent("2d listed gap");
    expect(screen.getByRole("button", {name: /Arsenal: BHA/})).toHaveTextContent("15:00");
    expect(within(table).getAllByText("DGW")).toHaveLength(2);
    expect(screen.getByRole("button", {name: /Arsenal: International break/}).closest("td")?.className).toContain("bg-yellow-100");
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:calendar");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await user.click(screen.getByRole("button", {name: "CSV"}));
    const csv = await new Promise<string>((resolve) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result as string);
      reader.readAsText(create.mock.calls[0][0] as Blob);
    });
    expect(csv).toContain("Sat · 2026-09-19");
    expect(csv).toContain("2d listed gap");
    expect(csv).toContain("No listed club fixture; rest unconfirmed");
    expect(csv).toContain("International break");
    expect(csv).toContain("AVL"); // A club game is retained even inside an international window.
    create.mockRestore(); click.mockRestore();
    await user.click(screen.getByRole("radio", {name: "Weekly"}));
    expect(screen.getByRole("table", {name: "All competitions by period"})).toBeVisible();
    expect(screen.getByText("DGW · 2 fixtures")).toBeVisible();
    expect(JSON.stringify([schedule, cups])).toBe(before);
  });
  it("clips Daily to exact dates while Weekly retains the whole DGW, and reset restores Weekly", async () => {
    const user = userEvent.setup();
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    await screen.findByRole("button", {name: /Arsenal: CUP/});
    await user.click(screen.getByRole("radio", {name: "Daily"}));
    await user.clear(screen.getByLabelText("Calendar from"));
    await user.type(screen.getByLabelText("Calendar from"), "2026-09-19");
    await user.clear(screen.getByLabelText("Calendar to"));
    await user.type(screen.getByLabelText("Calendar to"), "2026-09-19");
    expect(screen.getByRole("button", {name: /Arsenal: BHA/})).toHaveTextContent("2d listed gap");
    expect(screen.queryByRole("button", {name: /Arsenal: AVL/})).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", {name: "Weekly"}));
    expect(screen.getByRole("button", {name: /Arsenal: AVL/})).toBeVisible();
    await user.click(screen.getByRole("radio", {name: "Daily"}));
    await user.click(screen.getByRole("button", {name: "Reset calendar"}));
    expect(screen.getByRole("radio", {name: "Weekly"})).toBeChecked();
  });
  it("shows league difficulty, keeps cup blue, and supports a reversible empty range", async () => {
    const user = userEvent.setup();
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    const cup = await screen.findByRole("button", {name: /Arsenal: CUP/});
    expect(cup.className).toContain("bg-sky-100");
    expect(cup.textContent).toContain("LC");
    const international = screen.getByRole("button", { name: /Arsenal: International break/ });
    expect(international.closest("td")?.className).toContain("bg-yellow-100");
    expect(screen.getByText("DGW · 2 fixtures")).toBeVisible();
    await user.click(screen.getByRole("radio", {name: "Official FDR"}));
    expect(screen.getByRole("button", {name: /Arsenal: BHA/}).className).toContain("red");
    expect(cup.className).toContain("bg-sky-100");
    expect(international.closest("td")?.className).toContain("bg-yellow-100");
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
  it("keeps international breaks visible in an otherwise empty date range", async () => {
    const user = userEvent.setup();
    render(<CompetitiveFixtureCalendar teams={teams} schedule={schedule} fromGw={5} toGw={5} />);
    await screen.findByRole("button", {name: /Arsenal: CUP/});
    await user.clear(screen.getByLabelText("Calendar to"));
    await user.type(screen.getByLabelText("Calendar to"), "2026-10-01");
    await user.clear(screen.getByLabelText("Calendar from"));
    await user.type(screen.getByLabelText("Calendar from"), "2026-09-22");
    expect(screen.getByRole("button", {name: /Arsenal: International break/})).toBeVisible();
    expect(screen.queryByRole("button", {name: /Arsenal: BHA/})).not.toBeInTheDocument();
    expect(screen.queryByText("BGW")).not.toBeInTheDocument();
    expect(screen.getByText(/0 listed fixtures/)).toBeVisible();
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:calendar");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    await user.click(screen.getByRole("button", { name: "CSV" }));
    const csv = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsText(create.mock.calls[0][0] as Blob);
    });
    expect(csv).toContain("International break · 21 Sep–6 Oct");
    expect(csv).toContain("2026-09-21 – 2026-10-06");
    expect(csv).toContain("not confirmed player rest");
    expect(csv).toContain("https://www.premierleague.com/");
    create.mockRestore(); click.mockRestore();
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
