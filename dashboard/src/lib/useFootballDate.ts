import { useEffect, useState } from "react";
import { footballDate } from "./competitiveCalendar";

const today = () => footballDate(new Date(Date.now()).toISOString());

/** Roll open fixture views over at UK midnight, including after a sleeping tab resumes. */
export function useFootballDate(): string {
  const [date, setDate] = useState(today);
  useEffect(() => {
    const refresh = () => setDate(today());
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  return date;
}
