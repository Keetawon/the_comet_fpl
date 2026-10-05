import { useEffect, useState } from "react";
import { loadLiveFpl, type LiveFpl } from "@/data/liveFpl";

/** This feed has its own clock. It never makes an old SDP export or forecast look current. */
export function OfficialFplStatus() {
  const [live, setLive] = useState<LiveFpl | null | undefined>(undefined);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    let cancelled = false;
    loadLiveFpl().then(value => { if (!cancelled) setLive(value); });
    const tick = () => setNow(Date.now());
    const timer = window.setInterval(tick, 60_000);
    window.addEventListener("focus", tick);
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener("focus", tick); };
  }, []);
  if (import.meta.env.VITE_PUBLIC_DATA_POINTER !== "https://data.thecometfpl.com/current.json") return null;
  const overdue = live && now - Date.parse(live.captured_at) > 3 * 60 * 60 * 1000;
  return <aside aria-label="Official FPL updates" className="border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground lg:px-6">
    {live === undefined ? "Checking current official FPL reporting…" : live === null ?
      "Hourly FPL feed unavailable. Showing the last dashboard publication; check its source dates." : <>
        <strong className={overdue ? "text-amber-700 dark:text-amber-300" : ""}>
          Official FDR, injuries and prices{overdue ? " — update overdue" : ""}:
        </strong> {new Date(live.captured_at).toLocaleString()} · Hourly cloud refresh.
        {" "}Forecasts and match statistics keep their own dates.
      </>}
    {live !== undefined && <button type="button" className="ml-2 underline" onClick={() => window.location.reload()}>Check latest</button>}
  </aside>;
}
