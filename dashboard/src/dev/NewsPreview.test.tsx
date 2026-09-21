import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewsPage } from "@/pages/NewsPage";
import { loadNewsFeed, type PublicNewsFeed } from "@/data/newsFeed";
import LocalNewsPreview from "./NewsPreview";
import NewsRoundupPreview from "./NewsRoundupPreview";

vi.mock("@/data/newsFeed", async importOriginal => ({
  ...await importOriginal<typeof import("@/data/newsFeed")>(),
  loadNewsFeed: vi.fn(),
}));

beforeEach(() => {
  window.history.replaceState(null, "", "#news?preview=press-conferences");
  vi.mocked(loadNewsFeed).mockReset().mockResolvedValue({ schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-21T00:00:00Z", sources: [], stories: [], demo: false });
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("local press-conference simulation", () => {
  it("uses an explicitly synthetic feed without loading published news or enabling source/share links", async () => {
    render(<NewsPage />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    expect(loadNewsFeed).not.toHaveBeenCalled();
    expect(screen.getByRole("note")).toHaveTextContent("Synthetic examples");
    for (const article of screen.getAllByRole("article")) {
      expect(within(article).queryByRole("link")).not.toBeInTheDocument();
      for (const button of within(article).getAllByRole("button")) expect(button).toBeDisabled();
    }
  });

  it("keeps the preview selected through language changes and converts timetable time zones", async () => {
    render(<LocalNewsPreview />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    fireEvent.click(screen.getByRole("button", { name: "ไทย" }));
    expect(window.location.hash).toBe("#news?preview=press-conferences&lang=th");
    expect(screen.getByRole("heading", { name: /ไบรท์ตัน/ })).toBeInTheDocument();
    const timetable = screen.getByRole("region", { name: "ตารางแถลงข่าวจำลอง" });
    expect(within(timetable).getAllByText("09:00")).toHaveLength(3);
    fireEvent.change(within(timetable).getByRole("combobox", { name: "เขตเวลา" }), { target: { value: "Asia/Bangkok" } });
    expect(within(timetable).getAllByText("15:00")).toHaveLength(3);
    expect(within(timetable).getByText("21:30")).toBeInTheDocument();
  });

  it("filters timetable and news together, preserves an honest pending club, and resets", async () => {
    render(<LocalNewsPreview />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Club" }), { target: { value: "6" } });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByText("No news matches these filters.")).toBeInTheDocument();
    const timetable = screen.getByRole("region", { name: "Simulated press-conference schedule" });
    expect(within(timetable).getAllByRole("listitem")).toHaveLength(1);
    expect(within(timetable).getByText("Awaiting recap")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(within(timetable).getAllByRole("listitem")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Injury" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("ignores the preview query in production and loads the ordinary published feed", async () => {
    vi.stubEnv("DEV", false);
    render(<LocalNewsPreview />);
    await screen.findByText("No news has been published yet.");
    expect(loadNewsFeed).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Simulated press-conference schedule" })).not.toBeInTheDocument();
  });

  it("consolidates every sample club into a read-only bilingual message unaffected by card filters", async () => {
    render(<LocalNewsPreview />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    const box = screen.getByRole("textbox", { name: "All-team roundup text" });
    expect(box).toHaveAttribute("readonly");
    const text = (box as HTMLTextAreaElement).value;
    for (const club of ["ARSENAL", "BRIGHTON", "BOURNEMOUTH", "CHELSEA", "EVERTON", "SPURS"]) expect(text).toContain(`${club} |`);
    expect(text).toContain("SIMULATED NEWS ROUNDUP — NOT REAL NEWS");
    expect(text).toContain("No verified recap yet");
    expect(text).toContain("3/6 sample clubs");
    fireEvent.change(screen.getByRole("combobox", { name: "Club" }), { target: { value: "36" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Search news" }), { target: { value: "not-a-story" } });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(box).toHaveValue(text);
    fireEvent.click(screen.getByRole("button", { name: "ไทย" }));
    const translated = screen.getByRole("textbox", { name: "ข้อความสรุปข่าวทุกทีม" }) as HTMLTextAreaElement;
    expect(translated.value).toContain("ตัวอย่างสรุปข่าวสมมติ");
    expect(translated.value).toContain("ประเมินอีกครั้ง");
  });

  it("lets the owner preview collecting, conference completion and deadline-triggered editions", async () => {
    render(<LocalNewsPreview />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    expect(screen.getByText("After-conferences edition")).toBeInTheDocument();
    const timing = screen.getByRole("combobox", { name: "Preview timing" });
    fireEvent.change(timing, { target: { value: "collecting" } });
    expect(screen.queryByRole("textbox", { name: "All-team roundup text" })).not.toBeInTheDocument();
    expect(screen.getByText(/The roundup is not ready yet/)).toBeInTheDocument();
    fireEvent.change(timing, { target: { value: "deadline" } });
    expect(screen.getByText("Three-hours-before-deadline edition")).toBeInTheDocument();
    expect((screen.getByRole("textbox", { name: "All-team roundup text" }) as HTMLTextAreaElement).value).toContain("3/6 sample clubs");
    expect(loadNewsFeed).not.toHaveBeenCalled();
  });

  it("copies the entire labelled roundup and offers manual selection when clipboard access fails", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<LocalNewsPreview />);
    await screen.findByRole("heading", { name: /BRIGHTON/ });
    const box = screen.getByRole("textbox", { name: "All-team roundup text" }) as HTMLTextAreaElement;
    fireEvent.click(screen.getByRole("button", { name: "Copy full roundup" }));
    await screen.findByText("Full roundup copied");
    expect(writeText).toHaveBeenCalledWith(box.value);
    writeText.mockRejectedValueOnce(new Error("Clipboard denied"));
    fireEvent.click(screen.getByRole("button", { name: "Copy full roundup" }));
    await screen.findByText("Text selected. Use your device’s copy command.");
    expect(box.selectionStart).toBe(0);
    expect(box.selectionEnd).toBe(box.value.length);
    for (const share of screen.getAllByRole("button", { name: "Share" })) expect(share).toBeDisabled();
  });

  it("enforces the exact T-minus-three-hours boundary and explicit completed-conference evidence", () => {
    const feed: PublicNewsFeed = { schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-26T07:00:00Z", demo: true, sources: [], stories: [] };
    const props = { language: "en" as const, feed, clubs: [[3, "Arsenal"]] as const, deadline: "2026-09-26T10:00:00Z" };
    const { rerender } = render(<NewsRoundupPreview {...props} asOf="2026-09-26T06:59:59Z" allConferencesEndedAt="2026-09-26T07:00:01Z" />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    rerender(<NewsRoundupPreview {...props} asOf="2026-09-26T07:00:00Z" allConferencesEndedAt={null} />);
    expect(screen.getByText("Three-hours-before-deadline edition")).toBeInTheDocument();
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("0/1 sample clubs");
    rerender(<NewsRoundupPreview {...props} asOf="2026-09-25T15:00:00Z" allConferencesEndedAt="2026-09-25T15:00:00Z" />);
    expect(screen.getByText("After-conferences edition")).toBeInTheDocument();
    rerender(<NewsRoundupPreview {...props} asOf="2026-09-26T07:05:00Z" allConferencesEndedAt="2026-09-26T07:05:00Z" />);
    expect(screen.getByText("Three-hours-before-deadline edition")).toBeInTheDocument();
  });

  it("does not include stories or translations learned after the chosen edition", () => {
    const feed: PublicNewsFeed = { schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-26T07:00:00Z", demo: true, sources: [], stories: [] };
    const lateStory = { id: "a".repeat(64), source_id: "sample", source_kind: "x" as const, source_name: "Sample source", source_url: "https://x.com/FFScout/status/1", source_record_id: "1", source_sha256: "b".repeat(64), team_code: 3, team_name: "Arsenal", player_code: null, player_name: null, season: "2026-27", category: "squad" as const, title: { en: "Late update", th: "ข่าวภายหลัง" }, summary: { en: "Late information", th: "ข้อมูลภายหลัง" }, rendering: "ai_summary" as const, ai_model: "test", known_at: "2026-09-26T07:00:01Z", published_at: "2026-09-26T06:00:00Z", summarized_at: "2026-09-26T07:00:02Z" };
    const props = { language: "en" as const, clubs: [[3, "Arsenal"]] as const, asOf: "2026-09-26T07:00:00Z", deadline: "2026-09-26T10:00:00Z", allConferencesEndedAt: null };
    const { rerender } = render(<NewsRoundupPreview {...props} feed={{ ...feed, stories: [lateStory] }} />);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).not.toContain("Late information");
    rerender(<NewsRoundupPreview {...props} feed={{ ...feed, stories: [{ ...lateStory, known_at: "2026-09-26T06:30:00Z" }] }} />);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("No verified recap yet");
  });
});
