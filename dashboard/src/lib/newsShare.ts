/** Share published news only, never the current page's private filters or query. */
import type { PublicNewsFeed } from "@/data/newsFeed";

export type NewsLanguage = "en" | "th";

export function newsRoundupText(feed: PublicNewsFeed, language: NewsLanguage): string {
  const thai = language === "th";
  const stamp = (value: string) => new Date(value).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  // A source's printed club label is presentation only, never a player/team identity join.
  const label = (story: PublicNewsFeed["stories"][number]) => story.team_name || story.title.en.split(" | ")[0];
  const stories = [...feed.stories].sort((a, b) => label(a).localeCompare(label(b), "en") ||
    Date.parse(b.published_at || b.known_at) - Date.parse(a.published_at || a.known_at) || a.id.localeCompare(b.id));
  return [
    ...(feed.demo ? [thai ? "🧪 ข่าวสมมติ — ไม่ใช่ข่าวจริง" : "🧪 SIMULATED NEWS — NOT REAL NEWS"] : []),
    "THE COMET FPL · " + (thai ? "สรุปข่าวทุกทีม" : "All-team news roundup"),
    `${thai ? "เผยแพร่ชุดข่าว" : "Edition published"}: ${stamp(feed.generated_at)}`,
    thai ? "❌ ไม่พร้อมแน่นอน  |  ⚠️ ยังไม่แน่ชัด  |  ✅ ยืนยันว่าฟิต/พร้อม" : "❌ Unavailable  |  ⚠️ Doubtful / uncertain  |  ✅ Confirmed fit / available",
    thai ? "ซ้อมแล้วไม่ได้แปลว่าพร้อมลงเล่น · ไม่มีข้อมูลไม่ได้แปลว่าฟิต" : "Training alone does not confirm availability. No report does not mean fit.",
    "",
    ...stories.map(story => [
      label(story).toUpperCase(),
      // Preserve reviewed status lines verbatim. The browser never classifies players.
      thai && story.summary.th ? story.summary.th : (thai ? "[รอคำแปลไทย]\n" : "") + story.summary.en,
      `${thai ? "รายงานเมื่อ" : "Reported"}: ${stamp(story.published_at || story.known_at)}`,
      `${thai ? "ที่มา" : "Source"}: ${story.source_name}`,
      ...(feed.demo ? [] : [story.source_url]),
      "",
    ].join("\n")),
    ...(stories.length ? [] : [thai ? "ยังไม่มีข่าวที่ตรวจแล้ว" : "No reviewed reports available.", ""]),
    thai ? "📌 ข่าวจากแหล่งที่เลือก ไม่ใช่การยืนยันตัวจริงหรือการแถลงครบทุกทีม" : "📌 Selected-source reports, not a confirmed XI or proof that every conference has finished.",
    "THE COMET FPL",
    `https://www.thecometfpl.com/#news?lang=${language}`,
  ].join("\n");
}

/** Share the complete reviewed text, including branding and sources, only on demand. */
export async function shareNewsRoundup(text: string): Promise<"shared" | "copied" | "cancelled"> {
  if (navigator.share) {
    try {
      await navigator.share({ title: "THE COMET FPL · All-team news roundup", text });
      return "shared";
    } catch (error) {
      if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") return "cancelled";
    }
  }
  await navigator.clipboard.writeText(text);
  return "copied";
}

export function newsStoryUrl(id: string, language: NewsLanguage): string {
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) throw new Error("Invalid public story identity.");
  const query = new URLSearchParams({ story: id, lang: language });
  return `https://www.thecometfpl.com/#news?${query}`;
}

export function newsShareLinks(id: string, language: NewsLanguage, text: string) {
  const url = newsStoryUrl(id, language);
  return {
    url,
    line: `https://social-plugins.line.me/lineit/share?${new URLSearchParams({ url, text })}`,
    facebook: `https://www.facebook.com/sharer/sharer.php?${new URLSearchParams({ u: url })}`,
  };
}

export async function shareNews(id: string, language: NewsLanguage, text: string): Promise<"shared" | "copied" | "cancelled"> {
  const url = newsStoryUrl(id, language);
  if (navigator.share) {
    try {
      await navigator.share({ title: "THE COMET · Premier League news", text, url });
      return "shared";
    } catch (error) {
      if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") return "cancelled";
      // A denied or unsupported native share can still offer the public permalink.
    }
  }
  if (!navigator.clipboard?.writeText) throw new Error("Copy is unavailable in this browser. Use the story link.");
  await navigator.clipboard.writeText(url);
  return "copied";
}
