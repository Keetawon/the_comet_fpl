import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewsFeed } from "./NewsFeed";
import { loadNewsFeed, type NewsStory, type PublicNewsFeed } from "@/data/newsFeed";

vi.mock("@/data/newsFeed", () => ({ loadNewsFeed: vi.fn() }));
const mockLoad = vi.mocked(loadNewsFeed);

function story(index: number, overrides: Partial<NewsStory> = {}): NewsStory {
  return { id: String(index).repeat(64), source_id: "fpl", source_name: "FPL", source_kind: "fpl", source_url: "https://www.arsenal.com/news/update", source_record_id: `code:${index}`, published_at: "2026-09-18T09:00:00Z", known_at: `2026-09-19T${String(index + 6).padStart(2, "0")}:00:00Z`, source_sha256: "b".repeat(64), season: "2026-27", team_code: 3, team_name: "Arsenal", player_code: index, player_name: `Player ${index}`, category: "injury", title: { en: `Update ${index}`, th: `ข่าว ${index}` }, summary: { en: "The manager hopes the player will return. A return has not been confirmed.", th: "ผู้จัดการหวังว่านักเตะจะกลับมาได้ แต่ยังไม่ได้ยืนยัน" }, rendering: "ai_summary", ai_model: "gpt-test", summarized_at: "2026-09-19T11:30:00Z", ...overrides };
}
const fixture = (): PublicNewsFeed => ({ schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-19T12:00:00Z", demo: false, sources: [
  { source_id: "fpl", source_name: "FPL", source_kind: "fpl", status: "ok", last_checked_at: "2026-09-19T11:00:00Z", last_success_at: "2026-09-19T11:00:00Z", message: "Selected linked updates only." },
  { source_id: "x", source_name: "X sources", source_kind: "x", status: "pending_key", last_checked_at: null, last_success_at: null, message: "Not connected." },
], stories: [story(1), story(2, { category: "transfer", team_code: 8, team_name: "Chelsea" }), story(3, { category: "press_conference", title: { en: "Press briefing", th: null }, summary: { en: "A manager said he hopes to have the player back.", th: null }, rendering: "source_text", ai_model: null, summarized_at: null }), story(4)] });

beforeEach(() => { window.history.replaceState(null, "", "#news"); mockLoad.mockReset(); mockLoad.mockResolvedValue(fixture()); });

describe("published News feed", () => {
  it("shows attributed news, source timestamps, AI labels and limited source coverage", async () => {
    render(<NewsFeed />);
    await screen.findByRole("heading", { name: "Update 1" });
    expect(screen.getAllByText("AI summary")).toHaveLength(3);
    expect(screen.getAllByText(/FPL update · linked club article/)).toHaveLength(4);
    expect(screen.getAllByText(/FPL news updated/)).toHaveLength(4);
    expect(screen.getByText(/X sources · Not connected/)).toBeInTheDocument();
    expect(screen.getByText(/does not change xP/)).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Original source" });
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(links[0]).toHaveAttribute("href", "https://www.arsenal.com/news/update");
  });
  it("switches language without inventing a missing Thai translation", async () => {
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    fireEvent.click(screen.getByRole("button", { name: "ไทย" }));
    expect(screen.getByRole("heading", { name: "ข่าว 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Press briefing" })).toBeInTheDocument();
    expect(screen.getByText("รอคำแปลไทย · แสดงภาษาอังกฤษ")).toBeInTheDocument();
    expect(screen.getAllByText("ผู้จัดการหวังว่านักเตะจะกลับมาได้ แต่ยังไม่ได้ยืนยัน")).toHaveLength(3);
    expect(window.location.hash).toBe("#news?lang=th");
  });
  it("filters exact club codes/category/search consistently and resets", async () => {
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    fireEvent.change(screen.getByRole("combobox", { name: "Club" }), { target: { value: "8" } });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Update 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Injury" }));
    expect(screen.getByText("No news matches these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search news" }), { target: { value: "Press briefing" } });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getAllByRole("article")).toHaveLength(4);
  });
  it("keeps Summary compact to latest three by capture time without requesting a forecast", async () => {
    render(<NewsFeed compact />); await screen.findByRole("heading", { name: "Update 4" });
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "Update 1" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all news" })).toHaveAttribute("href", "#news?lang=en");
    expect(mockLoad).toHaveBeenCalledTimes(1);
  });
  it("keeps the Summary reading list lean while linking to the attributed full stories", async () => {
    render(<NewsFeed compact />); await screen.findByRole("heading", { name: "Update 4" });
    const cards = screen.getAllByRole("article");
    expect(within(cards[0]).getByRole("heading")).toHaveTextContent("Update 4");
    expect(within(cards[0]).getByRole("link", { name: "Update 4" })).toHaveAttribute("href", `#news?story=${"4".repeat(64)}&lang=en`);
    expect(within(cards[0]).getByText(/FPL news updated/)).toBeInTheDocument();
    expect(within(cards[0]).queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
    expect(screen.queryByText(/gpt-test/)).not.toBeInTheDocument();
  });
  it("synchronizes club shortcuts, topic counts and the search without inferring importance", async () => {
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    expect(screen.getByText("Newest captured first")).toBeInTheDocument();
    expect(screen.getAllByRole("article")[0]).toHaveAccessibleName("Update 4");
    fireEvent.click(screen.getByRole("button", { name: "Arsenal" }));
    expect(screen.getByRole("combobox", { name: "Club" })).toHaveValue("3");
    expect(screen.getByRole("button", { name: "Injury" })).toHaveTextContent("Injury2");
    expect(screen.getByRole("button", { name: "Transfer" })).toHaveTextContent("Transfer0");
    expect(screen.getByText("Showing 3 / 4 stories")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search news" }), { target: { value: "Press briefing" } });
    expect(screen.getByText("Showing 1 / 4 stories")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("button", { name: "Arsenal" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Showing 4 / 4 stories")).toBeInTheDocument();
  });
  it("keeps provider setup and model names behind closed details, while news dates stay visible", async () => {
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    const setup = screen.getByText(/X sources · Not connected/);
    expect(setup.closest("details")).not.toHaveAttribute("open");
    expect(setup).not.toBeVisible();
    for (const model of screen.getAllByText(/gpt-test/)) expect(model).not.toBeVisible();
    expect(screen.getAllByText(/FPL news updated/)[0]).toBeVisible();
    expect(screen.getAllByText("AI summary")[0]).toBeVisible();
  });
  it("loads the Thai shared story and highlights its card", async () => {
    window.history.replaceState(null, "", `#news?story=${"2".repeat(64)}&lang=th`);
    render(<NewsFeed />); const title = await screen.findByRole("heading", { name: "ข่าว 2" });
    expect(title.closest("article")).toHaveClass("ring-2");
  });
  it("labels a shared story absent from the current generation honestly", async () => {
    window.history.replaceState(null, "", `#news?story=${"9".repeat(64)}`);
    render(<NewsFeed />);
    expect(await screen.findByText(/This shared story is not in the current feed/)).toBeInTheDocument();
  });
  it("labels synthetic content and disables every share action", async () => {
    const value = fixture(); value.demo = true; mockLoad.mockResolvedValue(value);
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    expect(screen.getByText(/DEMO · Synthetic examples/)).toBeInTheDocument();
    for (const article of screen.getAllByRole("article")) {
      for (const button of within(article).getAllByRole("button")) expect(button).toBeDisabled();
    }
    expect(screen.queryByRole("link", { name: "Facebook" })).not.toBeInTheDocument();
  });
  it("shows pending sources and an honest empty state before credentials", async () => {
    const value = fixture(); value.stories = []; mockLoad.mockResolvedValue(value);
    render(<NewsFeed />);
    expect(await screen.findByText("No news has been published yet.")).toBeInTheDocument();
    expect(screen.getByText(/X sources · Not connected/)).toBeInTheDocument();
  });
  it("isolates optional feed failures from other dashboard content", async () => {
    mockLoad.mockRejectedValue(new Error("missing optional file"));
    render(<><p>Published forecast is intact</p><NewsFeed compact /></>);
    await waitFor(() => expect(screen.getByText(/News has not been published in this dashboard generation/)).toBeInTheDocument());
    expect(screen.getByText("Published forecast is intact")).toBeInTheDocument();
  });
  it("renders untrusted source markup as text and sharing links only contain public story data", async () => {
    const value = fixture(); value.stories = [story(1, { summary: { en: '<script>alert("x")</script>', th: null } })]; mockLoad.mockResolvedValue(value);
    render(<NewsFeed />); await screen.findByRole("heading", { name: "Update 1" });
    expect(screen.getByText('<script>alert("x")</script>')).toBeInTheDocument();
    expect(document.querySelector("article script")).toBeNull();
    const facebook = new URL(screen.getByRole("link", { name: "Facebook" }).getAttribute("href")!);
    expect([...facebook.searchParams.keys()]).toEqual(["u"]);
    expect(facebook.searchParams.get("u")).toContain(`story=${"1".repeat(64)}`);
  });
});
