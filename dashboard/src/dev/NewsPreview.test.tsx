import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewsPage } from "@/pages/NewsPage";
import { loadNewsFeed } from "@/data/newsFeed";
import LocalNewsPreview from "./NewsPreview";

vi.mock("@/data/newsFeed", async importOriginal => ({
  ...await importOriginal<typeof import("@/data/newsFeed")>(),
  loadNewsFeed: vi.fn(),
}));

beforeEach(() => {
  window.history.replaceState(null, "", "#news?preview=press-conferences");
  vi.mocked(loadNewsFeed).mockReset().mockResolvedValue({ schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-21T00:00:00Z", sources: [], stories: [], demo: false });
});
afterEach(() => vi.unstubAllEnvs());

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
});
