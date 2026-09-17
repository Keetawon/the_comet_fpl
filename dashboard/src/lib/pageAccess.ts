/** Hosted builds include the browser-only draft; optimizer services stay local. */
export function isHostedStatic(): boolean {
  return import.meta.env.VITE_HOSTED_STATIC === "true";
}

export function isPageAvailable(id: string): boolean {
  if (["team-analytics", "player-analytics"].includes(id)) return false;
  return !isHostedStatic() || !["next-gw", "plan-builder", "optimizer"].includes(id);
}
