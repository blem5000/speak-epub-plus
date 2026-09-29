import { invoke } from "@tauri-apps/api/core";

export const GITHUB_OWNER = "blem5000";
export const GITHUB_REPO = "speak-epub-plus";
export const RELEASES_LATEST_URL = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`;
export const DISMISS_KEY = "speakepub.dismissed-update";

export type UpdateInfo = {
  current: string;
  latest: string;
  url: string;
  notes: string;
  available: boolean;
};

type LatestRelease = { tag: string; url: string; notes: string };

/** Strip leading `v`, whitespace and build metadata for semver compare. */
export function normalizeVersion(v: string): string {
  return v.trim().replace(/^v/i, "").split("+")[0];
}

export function parseVersionParts(v: string): number[] {
  return normalizeVersion(v)
    .split(".")
    .map((p) => {
      const m = /^(\d+)/.exec(p.trim());
      return m ? parseInt(m[1], 10) : 0;
    });
}

/** -1 if a<b, 0 if equal, 1 if a>b. Non-numeric suffixes ignored. */
export function compareVersions(a: string, b: string): number {
  const pa = parseVersionParts(a);
  const pb = parseVersionParts(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return -1;
    if (x > y) return 1;
  }
  return 0;
}

export async function fetchLatestRelease(
  fetchFn: typeof fetch = globalThis.fetch
): Promise<LatestRelease | null> {
  try {
    const res = await fetchFn(RELEASES_LATEST_URL, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!res.ok) return null;
    const json = (await res.json()) as {
      tag_name?: unknown;
      html_url?: unknown;
      body?: unknown;
    };
    if (typeof json.tag_name !== "string" || typeof json.html_url !== "string") return null;
    return {
      tag: json.tag_name,
      url: json.html_url,
      notes: typeof json.body === "string" ? json.body.slice(0, 2000) : "",
    };
  } catch {
    return null;
  }
}

/**
 * Compare current app version against the latest GitHub Release.
 * Returns UpdateInfo only when a newer release exists, else null.
 * Silent on network errors / rate limits (no banner).
 */
export async function checkForUpdates(
  currentVersion: string,
  fetchFn: typeof fetch = globalThis.fetch
): Promise<UpdateInfo | null> {
  if (!currentVersion || !currentVersion.trim()) return null;
  const latest = await fetchLatestRelease(fetchFn);
  if (!latest) return null;
  const available = compareVersions(currentVersion, latest.tag) < 0;
  if (!available) return null;
  return {
    current: normalizeVersion(currentVersion),
    latest: normalizeVersion(latest.tag),
    url: latest.url,
    notes: latest.notes,
    available: true,
  };
}

/** Runtime app version via Tauri, null when unavailable (browser dev). */
export async function getCurrentVersion(): Promise<string | null> {
  try {
    const mod = await import("@tauri-apps/api/app");
    if (typeof mod.getVersion === "function") {
      const v = await mod.getVersion();
      if (typeof v === "string" && v.trim()) return v.trim();
    }
    return null;
  } catch {
    return null;
  }
}

export function isDismissed(latest: string): boolean {
  try {
    if (typeof window === "undefined" || !window.localStorage) return false;
    return window.localStorage.getItem(DISMISS_KEY) === normalizeVersion(latest);
  } catch {
    return false;
  }
}

export function dismissVersion(latest: string): void {
  try {
    if (typeof window === "undefined" || !window.localStorage) return;
    window.localStorage.setItem(DISMISS_KEY, normalizeVersion(latest));
  } catch {
    // ignore quota/private-mode errors
  }
}

/** Open the release page in the system browser (Tauri opener, fallback window.open). */
export async function openReleaseUrl(url: string): Promise<void> {
  const target = url.trim();
  if (!target) return;
  try {
    await invoke("plugin:opener|open_url", { url: target });
    return;
  } catch {
    try {
      window.open(target, "_blank", "noopener,noreferrer");
    } catch {
      // ignore
    }
  }
}
