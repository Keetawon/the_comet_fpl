/** Published calendar annotations only; never inferred from empty club schedules. */
export const INTERNATIONAL_BREAK_SOURCE = {
  name: "Premier League international calendar",
  url: "https://www.premierleague.com/en/news/4689113/when-are-the-international-breaks-for-202627",
  publishedOn: "2026-09-05",
  verifiedAt: "2026-09-15T08:35:18Z",
};

export interface InternationalBreak {
  season: string;
  from: string;
  to: string;
  label: string;
}

const WINDOWS: readonly InternationalBreak[] = [
  { season: "2026-27", from: "2026-09-21", to: "2026-10-06", label: "21 Sep–6 Oct" },
  { season: "2026-27", from: "2026-11-09", to: "2026-11-17", label: "9–17 Nov" },
  { season: "2026-27", from: "2027-03-22", to: "2027-03-30", label: "22–30 Mar" },
];

export function internationalBreaksForRange(season: string, from: string, to: string): InternationalBreak[] {
  if (!from || !to || from > to) return [];
  return WINDOWS.filter((w) => w.season === season && w.from <= to && w.to >= from);
}
