/** Hosted builds expose analytical pages; the trusted local build keeps decision tools. */
export function isHostedStatic(): boolean {
  return import.meta.env.VITE_HOSTED_STATIC === "true";
}

export function isPageAvailable(id: string): boolean {
  return !isHostedStatic() || !["next-gw", "plan-builder", "squad-draft", "optimizer"].includes(id);
}
