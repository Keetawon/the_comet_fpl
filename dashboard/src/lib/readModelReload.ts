/**
 * Republished dashboard JSON is cached at module scope by data/load.ts. A full document reload
 * is therefore the only honest way to fetch a just-published optimizer run in this static app.
 */
export function reloadPublishedReadModels(): void {
  window.location.reload();
}
