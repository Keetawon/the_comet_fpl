// FPL CDN image URLs, constructible client-side from the permanent `code` and
// `team_code` keys already present in the read models (both patterns verified 200 on
// 2026-08-16). The CDN is external: every <img> using these degrades to a neutral
// monogram on error (see components/Avatars.tsx), so a missing asset never renders
// wrong data -- only a fallback chip.

export function playerPhotoUrl(code: number): string {
  return `https://resources.premierleague.com/premierleague/photos/players/110x140/p${code}.png`;
}

export function teamBadgeUrl(teamCode: number): string {
  return `https://resources.premierleague.com/premierleague/badges/70/t${teamCode}.png`;
}
