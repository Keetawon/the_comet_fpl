import { lazy, Suspense } from "react";
import { NewsFeed } from "@/components/NewsFeed";

// Synthetic examples are excluded from the production build and published exports.
const LocalNewsPreview = import.meta.env.DEV ? lazy(() => import("@/dev/NewsPreview")) : null;

export function NewsPage() {
  if (LocalNewsPreview && new URLSearchParams(window.location.hash.split("?", 2)[1]).get("preview") === "press-conferences") {
    return <div className="mx-auto w-full max-w-[1600px] p-4 pb-8 lg:p-6"><Suspense fallback={<p role="status">Loading local preview…</p>}><LocalNewsPreview /></Suspense></div>;
  }
  return <div className="mx-auto w-full max-w-[1600px] p-4 pb-8 lg:p-6"><NewsFeed /></div>;
}
