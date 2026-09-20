/** Share public story identity only, never the current page's private filters or query. */
export type NewsLanguage = "en" | "th";

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
