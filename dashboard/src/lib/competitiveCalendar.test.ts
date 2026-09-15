import { describe, expect, it } from "vitest";
import { calendarColumns, calendarFixtures, calendarRange, footballDate, leagueSlot, visibleCalendar } from "./competitiveCalendar";

import { schedule, cups } from "@/data/competitiveSchedule.fixture";

describe("descriptive all-competition calendar", () => {
  it("keeps each DGW leg, adds cup identity without calling its round a GW", () => {
    const before = JSON.stringify([schedule, cups]);
    const rows = calendarFixtures(schedule, cups, "2026-27");
    expect(rows).toHaveLength(3);
    expect(rows.filter((r) => r.gw === 5)).toHaveLength(2);
    expect(rows.find((r) => r.source === "SDP")).toMatchObject({gw: null, fdr: null, competition: "LC"});
    expect(JSON.stringify([schedule, cups])).toBe(before);
    expect(calendarFixtures(schedule, cups, "2026-27")).toEqual(rows);
  });
  it("starts with the preceding midweek, omits empty days and filters exact clubs", () => {
    const all = calendarFixtures(schedule, cups, "2026-27");
    expect(calendarRange(all, 5, 5)).toEqual(["2026-09-14", "2026-09-21"]);
    expect(visibleCalendar(all, [3], "2026-09-14", "2026-09-21").dates).toEqual(["2026-09-16", "2026-09-19", "2026-09-21"]);
    expect(visibleCalendar(all, [36], "2026-09-14", "2026-09-21").rows).toEqual([]);
  });
  it("does not borrow another season or fabricate missing dates/venue", () => {
    expect(calendarFixtures(schedule, {...cups, season: "2025-26"}, "2026-27")).toHaveLength(2);
    const missing = structuredClone(cups);
    missing.competitions[0].matches[0].kickoff_time = null;
    const view = visibleCalendar(calendarFixtures(schedule, missing, "2026-27"), [3], "2026-09-14", "2026-09-21");
    expect(view.undated).toHaveLength(1);
    expect(view.rows).toHaveLength(2);
    expect(view.rows[1].fdr).toBeNull();
  });
  it("uses UK dates across DST and detects duplicate fixtures", () => {
    expect(footballDate("2026-09-16T23:30:00Z")).toBe("2026-09-17");
    expect(footballDate("2026-12-16T23:30:00Z")).toBe("2026-12-16");
    const duplicate = structuredClone(schedule);
    duplicate.teams[0].fixtures.push(duplicate.teams[0].fixtures[0]);
    expect(() => calendarFixtures(duplicate, cups, "2026-27")).toThrow("Duplicate");
  });
  it("groups Weekend / Midweek, keeping DGW legs and cup weekends", () => {
    const all = calendarFixtures(schedule, cups, "2026-27");
    const columns = calendarColumns(all);
    expect(columns.map((c) => [c.heading, c.label])).toEqual([["Midweek", "LC"], ["Weekend", "GW5"]]);
    expect(columns[1].fixtures).toHaveLength(2);
    expect(calendarColumns(all.map((f) => f.gw === null ? {...f, kickoff: "2026-09-19T19:00:00Z"} : f)).some((c) => c.heading === "Cup week")).toBe(true);
    expect(calendarColumns(all.map((f) => f.gw !== null ? {...f, kickoff: null} : f)).find((c) => c.label === "GW5")?.fixtures).toHaveLength(2);
  });
  it("distinguishes a published BGW from absent schedules and undated fixtures", () => {
    const blank = structuredClone(schedule);
    blank.teams.push({...blank.teams[0], team_code: 36, fixtures: []});
    expect(leagueSlot(blank, "2026-27", 3, 5)).toBe("DGW");
    expect(leagueSlot(blank, "2026-27", 36, 5)).toBe("BGW");
    expect(leagueSlot(blank, "2026-27", 999, 5)).toBe("UNAVAILABLE");
    expect(leagueSlot(blank, "2025-26", 36, 5)).toBe("UNAVAILABLE");
    expect(leagueSlot(blank, "2026-27", 36, 99)).toBe("UNAVAILABLE");
    blank.teams[0].fixtures[0].kickoff_time = null;
    expect(leagueSlot(blank, "2026-27", 3, 5)).toBe("DGW");
  });
});
