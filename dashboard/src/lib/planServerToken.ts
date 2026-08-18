export const PLAN_SERVER_TOKEN_STORAGE_KEY = "fpl-plan-server-token";

function normalized(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

/** A fragment parameter is never sent to the dashboard HTTP server. */
export function planServerTokenFromHash(hash = window.location.hash): string {
  const query = hash.split("?", 2)[1];
  if (!query) return "";
  return normalized(new URLSearchParams(query).get("server_token"));
}

/** Hash wins so a phone/LAN link can select the token for this tab explicitly. */
export function loadPlanServerToken(): string {
  const fromHash = planServerTokenFromHash();
  if (fromHash) return fromHash;
  try {
    return normalized(window.localStorage.getItem(PLAN_SERVER_TOKEN_STORAGE_KEY));
  } catch {
    return "";
  }
}

/** Returns false when storage is unavailable; the caller can retain the token in the hash. */
export function rememberPlanServerToken(token: string): boolean {
  try {
    const clean = normalized(token);
    if (clean) window.localStorage.setItem(PLAN_SERVER_TOKEN_STORAGE_KEY, clean);
    else window.localStorage.removeItem(PLAN_SERVER_TOKEN_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}
