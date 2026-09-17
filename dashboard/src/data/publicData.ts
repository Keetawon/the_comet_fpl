// Resolve one immutable public generation for the lifetime of this page. A failed
// pointer stays failed until reload; mixing it with older bundled files is unsafe.
const RELATIVE_FILE = /^(?:data|sdp)\/[a-z][a-z0-9_]*\.json$/;
const SHA256 = /^[0-9a-f]{64}$/;

interface Generation {
  base: URL;
  files: Record<string, { sha256: string; size_bytes: number }>;
}

let pinnedGeneration: Promise<Generation> | undefined;

function object(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

async function readGeneration(configuredPointer: string): Promise<Generation> {
  const endpoint = new URL(configuredPointer);
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash ||
      /[\\%?#]/.test(configuredPointer) || /(?:^|\/)\.\.?(?:\/|$)/.test(configuredPointer) ||
      !endpoint.pathname.endsWith("/current.json")) {
    throw new Error("Invalid dashboard data pointer URL.");
  }
  const response = await fetch(endpoint.href, {
    cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error(`Dashboard data generation unavailable (HTTP ${response.status}).`);
  const pointer: unknown = await response.json();
  if (!object(pointer) || pointer.schema !== "fpl.public-dashboard-current" || pointer.schema_version !== 1 ||
      typeof pointer.generation_sha256 !== "string" || !SHA256.test(pointer.generation_sha256) ||
      pointer.base_path !== `generations/${pointer.generation_sha256}` ||
      typeof pointer.published_at !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(pointer.published_at) ||
      !Number.isFinite(Date.parse(pointer.published_at)) || !object(pointer.files) || !Object.keys(pointer.files).length) {
    throw new Error("Invalid dashboard data generation pointer.");
  }
  for (const [relative, file] of Object.entries(pointer.files)) {
    if (!RELATIVE_FILE.test(relative) || !object(file) || Object.keys(file).length !== 2 ||
        typeof file.sha256 !== "string" || !SHA256.test(file.sha256) ||
        !Number.isSafeInteger(file.size_bytes) || (file.size_bytes as number) < 0) {
      throw new Error("Invalid dashboard data generation inventory.");
    }
  }
  const base = new URL(`${pointer.base_path}/`, endpoint);
  if (base.origin !== endpoint.origin) throw new Error("Dashboard data generation origin mismatch.");
  return { base, files: pointer.files as Generation["files"] };
}

export async function resolveDataUrl(relative: string): Promise<string> {
  if (!RELATIVE_FILE.test(relative)) throw new Error("Invalid dashboard data file path.");
  const pointer = import.meta.env.VITE_PUBLIC_DATA_POINTER?.trim();
  if (!pointer) {
    const [directory, filename] = relative.split("/");
    const base = directory === "data"
      ? import.meta.env.VITE_DATA_BASE ?? "/data"
      : import.meta.env.VITE_SDP_DATA_BASE ?? `${import.meta.env.BASE_URL}sdp`;
    return `${base}/${filename}`;
  }
  const generation = await (pinnedGeneration ??= readGeneration(pointer));
  if (!Object.hasOwn(generation.files, relative)) {
    throw new Error(`Dashboard data generation does not contain ${relative}.`);
  }
  return new URL(relative, generation.base).href;
}
