// Official availability status codes -> labels. Reported overlay only: it never folds
// into xP and never means "starts".

export const AVAILABILITY_LABEL: Record<string, string> = {
  a: "available",
  d: "doubtful",
  i: "injured",
  s: "suspended",
  u: "unavailable",
  n: "not available",
  x: "not announced",
};

export function availabilityLabel(status: string | null): string {
  if (status == null) return "–";
  return AVAILABILITY_LABEL[status] ?? status;
}
