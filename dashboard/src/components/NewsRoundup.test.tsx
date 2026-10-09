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
  ["2026-10-10T04:59:59Z", false], ["2026-10-10T05:00:00Z", true], ["2026-10-10T10:00:00Z", false],
])("opens only in the five-hour pre-deadline window at %s", (time, visible) => {
  vi.useFakeTimers(); vi.setSystemTime(new Date(time));
  render(<NewsRoundup feed={feed} language="en" />);
  expect(Boolean(screen.queryByText(/Read the reviewed roundup/))).toBe(visible);
});
it("withholds stale editions and never claims every conference is complete", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-10T05:00:00Z"));
  render(<NewsRoundup feed={{ ...feed, generated_at: "2026-10-08T18:00:00Z" }} language="en" />);
  expect(screen.queryByText(/Read the reviewed roundup/)).toBeNull();
  expect(screen.getByText(/over 24 hours old/)).toBeTruthy();
  expect(screen.getByText(/does not establish/)).toBeTruthy();
});
