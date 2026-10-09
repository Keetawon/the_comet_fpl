import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NewsRoundup } from "./NewsRoundup";
import type { PublicNewsFeed } from "@/data/newsFeed";

const feed: PublicNewsFeed = {
  schema: "fpl.public-news", schema_version: 2, semantics: "reported_news_not_forecast", demo: false,
  generated_at: "2026-10-09T18:00:00Z", stories: [], sources: [],
  roundup: { season: "2026-27", gw: 8, deadline_at: "2026-10-10T10:00:00Z", opens_at: "2026-10-10T05:00:00Z", schedule_captured_at: "2026-10-09T18:00:00Z", schedule_sha256: "a".repeat(64) },
};
afterEach(() => { cleanup(); vi.useRealTimers(); });
it.each([
  "2026-10-09T18:00:00Z", "2026-10-10T04:59:59Z", "2026-10-10T05:00:00Z", "2026-10-10T10:00:00Z",
])("shows updates immediately, including outside the old window at %s", time => {
  vi.useFakeTimers(); vi.setSystemTime(new Date(time));
  render(<NewsRoundup feed={feed} language="en" />);
  expect(screen.getByText(/Read the reviewed roundup/)).toBeTruthy();
  expect(screen.queryByText(/Opens five hours/)).toBeNull();
});
it("labels stale editions without hiding updates or claiming conference completion", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-10T05:00:00Z"));
  render(<NewsRoundup feed={{ ...feed, generated_at: "2026-10-08T18:00:00Z" }} language="en" />);
  expect(screen.getByText(/Read the reviewed roundup/)).toBeTruthy();
  expect(screen.getByText(/over 24 hours old/)).toBeTruthy();
  expect(screen.getByText(/does not establish/)).toBeTruthy();
});
it("shows updates without a deadline schedule, in both languages", () => {
  const legacy: PublicNewsFeed = { ...feed, schema_version: 1 };
  delete legacy.roundup;
  const { rerender } = render(<NewsRoundup feed={legacy} language="en" />);
  expect(screen.getByText(/Read the reviewed roundup/)).toBeTruthy();
  rerender(<NewsRoundup feed={legacy} language="th" />);
  expect(screen.getByText("แสดงข่าวทันทีที่ตรวจและเผยแพร่แล้ว")).toBeTruthy();
  expect(screen.getByText(/อ่านสรุปข่าวที่ตรวจแล้ว/)).toBeTruthy();
});
