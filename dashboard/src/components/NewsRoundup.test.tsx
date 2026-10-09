import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NewsRoundup } from "./NewsRoundup";
import type { PublicNewsFeed } from "@/data/newsFeed";

const feed: PublicNewsFeed = {
  schema: "fpl.public-news", schema_version: 2, semantics: "reported_news_not_forecast", demo: false,
  generated_at: "2026-10-09T18:00:00Z", stories: [], sources: [],
  roundup: { season: "2026-27", gw: 8, deadline_at: "2026-10-10T10:00:00Z", opens_at: "2026-10-10T05:00:00Z", schedule_captured_at: "2026-10-09T18:00:00Z", schedule_sha256: "a".repeat(64) },
};
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
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

it("copies all sorted source reports verbatim with attribution and branding, with manual fallback", async () => {
  const story: PublicNewsFeed["stories"][number] = {
    id: "a".repeat(64), source_id: "scout", source_name: "Scout", source_kind: "x",
    source_url: "https://x.com/Scout/status/1", source_record_id: "1", source_sha256: "b".repeat(64),
    known_at: feed.generated_at, published_at: "2026-10-09T12:00:00Z", summarized_at: feed.generated_at,
    season: null, team_code: null, team_name: null, player_code: null, player_name: null,
    category: "squad", title: { en: "B CLUB | Team news", th: "B CLUB | ข่าวทีม" },
    summary: { en: "❌ Out Player\n⚠️ Training Player (training only)\n✅ Ready Player", th: "❌ Out Player\n⚠️ Training Player (ซ้อมแล้ว ยังไม่ยืนยันความพร้อม)\n✅ Ready Player" },
    rendering: "ai_summary", ai_model: "reviewed-test",
  };
  const edition = { ...feed, stories: [story, { ...story, id: "c".repeat(64), title: { en: "A CLUB | Team news", th: null }, summary: { en: "No status has been confirmed.", th: null } }] };
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const { rerender } = render(<NewsRoundup feed={edition} language="en" />);
  const box = screen.getByRole("textbox", { name: "All-team roundup text" }) as HTMLTextAreaElement;
  const text = box.value;
  expect(box).toHaveAttribute("readonly");
  expect(text.indexOf("A CLUB")).toBeLessThan(text.indexOf("B CLUB"));
  expect(text).toContain(story.summary.en);
  expect(text).toContain("No status has been confirmed.");
  expect(text).toContain("Reported: 2026-10-09 12:00 UTC\nSource: Scout\nhttps://x.com/Scout/status/1");
  expect(text).toContain("THE COMET FPL\nhttps://www.thecometfpl.com/#news?lang=en");
  fireEvent.click(screen.getByRole("button", { name: "Copy all teams" }));
  await screen.findByText("All-team roundup copied.");
  expect(writeText).toHaveBeenCalledWith(text);
  writeText.mockRejectedValueOnce(new Error("Clipboard denied"));
  fireEvent.click(screen.getByRole("button", { name: "Copy all teams" }));
  await screen.findByText("All text selected. Use your device’s copy command.");
  expect(box.selectionStart).toBe(0); expect(box.selectionEnd).toBe(text.length);
  rerender(<NewsRoundup feed={edition} language="th" />);
  const translated = screen.getByRole("textbox", { name: "ข้อความสรุปข่าวทุกทีม" }) as HTMLTextAreaElement;
  expect(translated.value).toContain(story.summary.th);
  expect(translated.value).toContain("[รอคำแปลไทย]\nNo status has been confirmed.");
  expect(translated.value).toContain("#news?lang=th");
  expect(screen.queryByText("All-team roundup copied.")).toBeNull();
  rerender(<NewsRoundup feed={{ ...edition, demo: true }} language="en" />);
  expect(screen.getByRole("button", { name: "Share all teams" })).toBeDisabled();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("SIMULATED NEWS");
});
