import { describe, expect, it } from "vitest";
import { calendarColumns, calendarFixtures, calendarRange, dailyCalendarColumns, listedClubGaps, footballDate, leagueSlot, visibleCalendar } from "./competitiveCalendar";

import { schedule, cups } from "@/data/competitiveSchedule.fixture";
import { internationalBreaksForRange } from "@/data/internationalBreaks";

describe("descriptive all-competition calendar", () => {
  it("keeps every daily date, all DGW legs and overlapping international annotations", () => {
    const rows = calendarFixtures(schedule, cups, "2026-27");
    const before = JSON.stringify(rows);
    const breaks = internationalBreaksForRange("2026-27", "2026-09-14", "2026-09-22");
    const columns = dailyCalendarColumns(rows, "2026-09-14", "2026-09-22", breaks);
    expect(columns).toHaveLength(9);
    expect(columns[0]).toMatchObject({ heading: "Mon", label: "14 Sept", fixtures: [] });
    expect(columns[5].fixtures).toHaveLength(1);
    expect(columns[7].fixtures).toHaveLength(1);
    expect(columns[7].internationalBreak?.from).toBe("2026-09-21");
    expect(columns[8].internationalBreak).toBeDefined();
    expect(columns[8].fixtures).toEqual([]);
    expect(columns.flatMap((c) => c.fixtures)).toEqual(rows);
    expect(dailyCalendarColumns([...rows].reverse(), "2026-09-14", "2026-09-22", breaks)).toEqual(columns);
    expect(JSON.stringify(rows)).toBe(before);
    expect(dailyCalendarColumns(rows, "2026-09-19", "2026-09-19")[0].fixtures).toHaveLength(1);
    expect(dailyCalendarColumns(rows, "", "2026-09-19")).toEqual([]);
    expect(dailyCalendarColumns(rows, "2026-09-20", "2026-09-19")).toEqual([]);
    expect(() => dailyCalendarColumns(rows, "2026-01-01", "2030-01-01")).toThrow("366 days");
  });
  it("counts clear dates between listed games, retaining predecessors outside the visible range", () => {
    const rows = calendarFixtures(schedule, cups, "2026-27");
    const before = JSON.stringify(rows);
    const gaps = listedClubGaps(rows);
    expect(gaps.has(rows[0].key)).toBe(false);
    expect(gaps.get(rows[1].key)).toMatchObject({ days: 2, previousKickoff: rows[0].kickoff });
    expect(gaps.get(rows[2].key)?.days).toBe(1);
    const oneDay = dailyCalendarColumns(rows, "2026-09-19", "2026-09-19");
    expect(gaps.get(oneDay[0].fixtures[0].key)?.days).toBe(2);
    expect(listedClubGaps([...rows].reverse())).toEqual(gaps);
    expect(listedClubGaps([...rows, { ...rows[0], key: "undated", kickoff: null }]).size).toBe(0);
    expect(listedClubGaps([{ ...rows[0], teamCode: 36 }, ...rows.slice(1)]).has(rows[1].key)).toBe(false);
    expect(JSON.stringify(rows)).toBe(before);
  });
  it("uses UK dates across DST and keeps multiple games on one day", () => {
    const base = calendarFixtures(schedule, cups, "2026-27")[0];
    const rows = [
      { ...base, key: "a", kickoff: "2026-10-24T23:30:00Z" },
      { ...base, key: "b", kickoff: "2026-10-25T14:00:00Z" },
      { ...base, key: "c", kickoff: "2026-10-27T00:30:00Z" },
    ];
    const columns = dailyCalendarColumns(rows, "2026-10-24", "2026-10-27");
    expect(columns).toHaveLength(4);
    expect(columns[0].fixtures).toEqual([]);
    expect(columns[1].fixtures).toHaveLength(2);
    expect(listedClubGaps(rows).get("b")?.days).toBe(0);
    expect(listedClubGaps(rows).get("c")?.days).toBe(1);
  });
  it("adds verified international windows without creating fixtures or hiding overlapping DGW legs", () => {
    const rows = calendarFixtures(schedule, cups, "2026-27");
    const windows = internationalBreaksForRange("2026-27", "2026-09-01", "2027-05-31");
    expect(windows.map((w) => [w.from, w.to])).toEqual([
      ["2026-09-21", "2026-10-06"], ["2026-11-09", "2026-11-17"], ["2027-03-22", "2027-03-30"],
    ]);
    const columns = calendarColumns(rows, windows);
    expect(columns.flatMap((c) => c.fixtures)).toEqual(calendarColumns(rows).flatMap((c) => c.fixtures));
    expect(columns.filter((c) => c.heading === "International break")).toHaveLength(3);
    expect(columns.find((c) => c.label === "GW5")?.fixtures).toHaveLength(2);
    expect(calendarColumns([], internationalBreaksForRange("2026-27", "2026-09-22", "2026-10-01"))).toMatchObject([
      { heading: "International break", from: "2026-09-21", to: "2026-10-06", fixtures: [] },
    ]);
    expect(internationalBreaksForRange("2026-27", "2026-10-06", "2026-10-06")).toHaveLength(1);
    expect(internationalBreaksForRange("2026-27", "2026-10-07", "2026-11-08")).toEqual([]);
    expect(internationalBreaksForRange("2027-28", "2026-09-01", "2027-05-31")).toEqual([]);
    expect(internationalBreaksForRange("2026-27", "", "2026-11-08")).toEqual([]);
    expect(internationalBreaksForRange("2026-27", "2026-11-08", "2026-09-01")).toEqual([]);
  });
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
