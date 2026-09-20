/** User-triggered sharing of already composed public text; never reads page or manager state. */
const SITE_URL = "https://www.thecometfpl.com/";
// Application bound, not a claim about LINE's maximum; never truncate a briefing.
const MAX_LINE_URL_LENGTH = 8_000;

function requireText(text: string): void {
  if (!text.trim()) throw new Error("There is no briefing text to share.");
}

export async function copyGwBriefing(text: string): Promise<void> {
  requireText(text);
  if (!navigator.clipboard?.writeText) throw new Error("Copy is unavailable. Download the text instead.");
  await navigator.clipboard.writeText(text);
}

export async function shareGwBriefing(text: string): Promise<"shared" | "copied" | "cancelled"> {
  requireText(text);
  if (navigator.share) {
    try {
      await navigator.share({ title: "THE COMET · Gameweek briefing", text });
      return "shared";
    } catch (error) {
      if (typeof error === "object" && error !== null && "name" in error && error.name === "AbortError") return "cancelled";
    }
  }
  await copyGwBriefing(text);
  return "copied";
}

/** Null means use native share, copy or download; the full text is never shortened. */
export function gwBriefingLineUrl(text: string): string | null {
  requireText(text);
  const url = `https://social-plugins.line.me/lineit/share?${new URLSearchParams({ url: SITE_URL, text })}`;
  return url.length <= MAX_LINE_URL_LENGTH ? url : null;
}

/** Copy first, then let the UI offer this link; opening/posting remains a user action. */
export async function prepareGwBriefingFacebook(text: string): Promise<{ url: string; instruction: string }> {
  await copyGwBriefing(text);
  return {
    url: `https://www.facebook.com/sharer/sharer.php?${new URLSearchParams({ u: SITE_URL })}`,
    instruction: "Briefing copied. Open Facebook and paste the text into your post; Facebook may not prefill it.",
  };
}

export function downloadGwBriefing(text: string): void {
  requireText(text);
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "the-comet-gameweek-briefing.txt";
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    // Let the browser start consuming the blob before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }
}
