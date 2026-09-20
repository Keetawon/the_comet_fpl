import { resolveDataUrl } from "./publicData";

export type NewsCategory = "injury" | "suspension" | "transfer" | "squad" | "press_conference" | "other";
export interface NewsSource {
  source_id: string;
  source_name: string;
  source_kind: "fpl" | "x";
  status: "ok" | "disabled" | "pending_key" | "error" | "budget_exhausted" | "not_configured";
  last_checked_at: string | null;
  last_success_at: string | null;
  message: string;
}
export interface NewsStory {
  id: string;
  source_id: string;
  source_name: string;
  source_kind: "fpl" | "x";
  source_url: string;
  source_record_id: string;
  published_at: string | null;
  known_at: string;
  source_sha256: string;
  season: string | null;
  team_code: number | null;
  team_name: string | null;
  player_code: number | null;
  player_name: string | null;
  category: NewsCategory;
  title: { en: string; th: string | null };
  summary: { en: string; th: string | null };
  rendering: "source_text" | "ai_summary";
  ai_model: string | null;
  summarized_at: string | null;
}
export interface PublicNewsFeed {
  schema: "fpl.public-news";
  schema_version: 1;
  semantics: "reported_news_not_forecast";
  generated_at: string;
  demo: boolean;
  sources: NewsSource[];
  stories: NewsStory[];
}

const HASH = /^[a-f0-9]{64}$/;
const CATEGORIES = ["injury", "suspension", "transfer", "squad", "press_conference", "other"];
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= 6000;
const nullableText = (value: unknown): boolean => value === null || text(value);
const date = (value: unknown): value is string => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const nullableDate = (value: unknown): boolean => value === null || date(value);
const code = (value: unknown): boolean => value === null || (Number.isSafeInteger(value) && (value as number) > 0);
const exactKeys = (value: Record<string, unknown>, keys: string): boolean => Object.keys(value).sort().join(",") === keys.split(" ").sort().join(",");
const bilingual = (value: unknown): boolean => object(value) && exactKeys(value, "en th") && text(value.en) && nullableText(value.th);

export function safeNewsSourceUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 2048 || /[\\\s]/.test(value)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.port && !url.hash &&
      /^(?:[a-z0-9-]+\.)+[a-z]{2,}$/i.test(url.hostname) &&
      !/(?:^|\.)(?:localhost|local|internal|test|invalid|example)$/i.test(url.hostname) &&
      ![...url.searchParams.keys()].some(key => /token|secret|password|manager|entry|squad|api.?key|signature|auth/i.test(key));
  } catch { return false; }
}

/** Public sidecar only: no private notes, manager inputs, forecast fields or client AI. */
export function parseNewsFeed(value: unknown): PublicNewsFeed {
  if (!object(value) || !exactKeys(value, "schema schema_version semantics generated_at demo sources stories") ||
      value.schema !== "fpl.public-news" || value.schema_version !== 1 || value.semantics !== "reported_news_not_forecast" ||
      !date(value.generated_at) || typeof value.demo !== "boolean" || !Array.isArray(value.sources) || !Array.isArray(value.stories) ||
      value.sources.length > 50 || value.stories.length > 100) throw new Error("Invalid published news feed.");
  const sourceIds = new Map<string, Record<string, unknown>>();
  for (const source of value.sources) {
    if (!object(source) || !exactKeys(source, "source_id source_name source_kind status last_checked_at last_success_at message") ||
        !text(source.source_id) || sourceIds.has(source.source_id) || !text(source.source_name) || !["fpl", "x"].includes(String(source.source_kind)) ||
        !["ok", "disabled", "pending_key", "error", "budget_exhausted", "not_configured"].includes(String(source.status)) ||
        !nullableDate(source.last_checked_at) || !nullableDate(source.last_success_at) || typeof source.message !== "string" ||
        [source.last_checked_at, source.last_success_at].some(at => date(at) && Date.parse(at) > Date.parse(value.generated_at as string)) ||
        (date(source.last_checked_at) && date(source.last_success_at) && Date.parse(source.last_success_at) > Date.parse(source.last_checked_at))) throw new Error("Invalid news source status.");
    sourceIds.set(source.source_id, source);
  }
  const ids = new Set<string>();
  const records = new Set<string>();
  for (const story of value.stories) {
    if (!object(story) || !exactKeys(story, "id source_id source_name source_kind source_url source_record_id published_at known_at source_sha256 season team_code team_name player_code player_name category title summary rendering ai_model summarized_at") ||
        typeof story.id !== "string" || !HASH.test(story.id) || ids.has(story.id) || !text(story.source_id) ||
        !text(story.source_name) || !text(story.source_record_id) || !safeNewsSourceUrl(story.source_url) ||
        !date(story.known_at) || !nullableDate(story.published_at) || !nullableDate(story.summarized_at) ||
        typeof story.source_sha256 !== "string" || !HASH.test(story.source_sha256) ||
        !nullableText(story.season) || !code(story.team_code) || !code(story.player_code) ||
        !nullableText(story.team_name) || !nullableText(story.player_name) ||
        (story.team_code === null) !== (story.team_name === null) || (story.player_code === null) !== (story.player_name === null) ||
        !CATEGORIES.includes(String(story.category)) ||
        !bilingual(story.title) || !bilingual(story.summary) || !["source_text", "ai_summary"].includes(String(story.rendering)) ||
        !nullableText(story.ai_model) ||
        [story.known_at, story.summarized_at].some(at => date(at) && Date.parse(at) > Date.parse(value.generated_at as string)) ||
        (date(story.published_at) && Date.parse(story.published_at) > Date.parse(story.known_at)) ||
        (story.rendering === "source_text" && (story.ai_model !== null || story.summarized_at !== null)) ||
        (story.rendering === "ai_summary" && (story.ai_model === null || story.summarized_at === null ||
          (story.title as Record<string, unknown>).th === null || (story.summary as Record<string, unknown>).th === null))) throw new Error("Invalid published news story.");
    const source = sourceIds.get(story.source_id);
    if (!source || source.source_kind !== story.source_kind || source.source_name !== story.source_name) throw new Error("News story source mismatch.");
    if (story.source_kind === "x" && (!/^https:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/[A-Za-z0-9_]{1,15}\/status\/\d+$/.test(story.source_url) || story.player_code !== null)) throw new Error("Invalid X source permalink or player identity.");
    const record = JSON.stringify([story.source_id, story.source_record_id]);
    if (records.has(record)) throw new Error("Duplicate published news source record.");
    records.add(record);
    ids.add(story.id);
  }
  return value as unknown as PublicNewsFeed;
}

export async function loadNewsFeed(): Promise<PublicNewsFeed> {
  const url = await resolveDataUrl("sdp/news_feed.json");
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000), redirect: "error" });
  if (!response.ok) throw new Error("News is not available in this published generation.");
  return parseNewsFeed(await response.json());
}
