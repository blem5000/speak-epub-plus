import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getStore, setStore } from "@/lib/sidecar";

export const GITHUB_OWNER = "blem5000";
export const GITHUB_REPO = "speak-epub-plus";
export const RELEASES_LATEST_URL = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`;
export const PORTABLE_ASSET_PATTERN = /-x64-portable\.zip$/i;

export type UpdateInfo = {
  current: string;
  latest: string;
  url: string;
  notes: string;
  available: boolean;
  /** browser_download_url of the portable ZIP asset ("" when release has none). */
  zipUrl: string;
  /** asset size in bytes (0 when unknown). */
  zipSize: number;
  /** the update came from the signed manifest (Tauri updater plugin). */
  signed?: boolean;
};

export type UpdatePrefs = { auto: boolean; skipped: string };
export type DownloadProgress = { received: number; total: number };

/** The signed update object (Tauri updater plugin), kept for the install. */
type SignedUpdate = {
  version: string;
  currentVersion: string;
  body?: string;
  length?: number;
  downloadAndInstall: (
    onEvent?: (progress: { event: string; data?: { contentLength?: number; chunkLength?: number } }) => void,
    options?: unknown
  ) => Promise<void>;
};

let signedUpdate: SignedUpdate | null = null;

type LatestRelease = {
  tag: string;
  url: string;
  notes: string;
  zipUrl: string;
  zipSize: number;
};

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
      assets?: unknown;
    };
    if (typeof json.tag_name !== "string" || typeof json.html_url !== "string") return null;
    const assets = Array.isArray(json.assets)
      ? (json.assets as Array<Record<string, unknown>>)
      : [];
    const pick =
      assets.find(
        (a) => typeof a.name === "string" && PORTABLE_ASSET_PATTERN.test(a.name as string)
      ) ?? assets.find((a) => typeof a.name === "string" && (a.name as string).endsWith(".zip"));
    const zipUrl =
      pick && typeof pick.browser_download_url === "string" ? pick.browser_download_url : "";
    const zipSize = pick && typeof pick.size === "number" ? pick.size : 0;
    return {
      tag: json.tag_name,
      url: json.html_url,
      notes: typeof json.body === "string" ? json.body.slice(0, 2000) : "",
      zipUrl,
      zipSize,
    };
  } catch {
    return null;
  }
}

/**
 * The signed update check (Tauri updater plugin).
 *
 * The release publishes `latest.json` signed with the release key; the app
 * verifies that signature with the public key baked into the binary, so a
 * tampered manifest (or a MITM) can never point the app at another payload.
 * Returns null when there is no update, the plugin is unavailable, or the
 * manifest does not verify.
 */
async function checkSignedUpdate(): Promise<UpdateInfo | null> {
  try {
    const mod = await import("@tauri-apps/plugin-updater");
    const update = (await mod.check()) as unknown as SignedUpdate;
    if (!update || !update.version) {
      // the manifest was fetched and its signature verified — there is just
      // no newer release
      void logToApp("signed update check: manifest verified, no newer release");
      return null;
    }
    signedUpdate = update;
    // record the result — the GUI has no console, the log file is the only
    // way to see that the signed manifest verified (or did not)
    void logToApp(`signed update check: ${update.currentVersion} -> ${update.version} (manifest verified)`);
    return {
      current: normalizeVersion(update.currentVersion ?? ""),
      latest: normalizeVersion(update.version),
      url: `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/tag/v${update.version}`,
      notes: typeof update.body === "string" ? update.body.slice(0, 2000) : "",
      available: true,
      zipUrl: "",
      zipSize: typeof update.length === "number" ? update.length : 0,
      signed: true,
    };
  } catch (err) {
    // no update, offline, or the signature did not verify
    signedUpdate = null;
    void logToApp(
      `signed update check: none (${err instanceof Error ? err.message : String(err)})`
    );
    return null;
  }
}

/** Write a line into the app log file (Rust side). */
async function logToApp(line: string): Promise<void> {
  try {
    await invoke("app_log_line", { line });
  } catch {
    // logging is best-effort
  }
}

/**
 * Compare current app version against the latest release.
 * The signed manifest is preferred; the GitHub API is the fallback (it also
 * provides the portable ZIP that the portable build installs from).
 */
export async function checkForUpdates(
  currentVersion: string,
  fetchFn: typeof fetch = globalThis.fetch
): Promise<UpdateInfo | null> {
  if (!currentVersion || !currentVersion.trim()) return null;
  const signed = await checkSignedUpdate();
  if (signed) {
    // the signed manifest wins: it is verified against the release key
    if (compareVersions(currentVersion, signed.latest) < 0) return signed;
    return null;
  }
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
    zipUrl: latest.zipUrl,
    zipSize: latest.zipSize,
    signed: false,
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

/** Update prefs persisted in the Python store (`updateAuto`, `updateSkipped`). */
export async function getUpdatePrefs(opts?: { signal?: AbortSignal }): Promise<UpdatePrefs> {
  try {
    const res = await getStore(opts);
    const store = (res?.result ?? {}) as Record<string, unknown>;
    return {
      auto: store.updateAuto !== false,
      skipped:
        typeof store.updateSkipped === "string" && store.updateSkipped.trim()
          ? normalizeVersion(store.updateSkipped)
          : "",
    };
  } catch {
    return { auto: true, skipped: "" };
  }
}

export async function setAutoUpdate(on: boolean): Promise<void> {
  try {
    await setStore({ updateAuto: on });
  } catch {
    // pref write is best-effort; default stays "auto on"
  }
}

/** "Skip this version" — remembered across sessions until that tag is outrun. */
export async function skipVersion(latest: string): Promise<void> {
  try {
    await setStore({ updateSkipped: normalizeVersion(latest) });
  } catch {
    // ignore
  }
}

type UpdateFoundListener = (info: UpdateInfo) => void;
const updateFoundListeners = new Set<UpdateFoundListener>();

export function onUpdateFound(fn: UpdateFoundListener): () => void {
  updateFoundListeners.add(fn);
  return () => {
    updateFoundListeners.delete(fn);
  };
}

export function announceUpdateFound(info: UpdateInfo): void {
  for (const fn of Array.from(updateFoundListeners)) {
    try {
      fn(info);
    } catch {
      // listener errors never break the checker
    }
  }
}

/** Settings-triggered check: ignores auto/skip prefs and surfaces the banner. */
export async function manualCheck(): Promise<UpdateInfo | null> {
  const current = await getCurrentVersion();
  if (!current) return null;
  const info = await checkForUpdates(current);
  if (info) announceUpdateFound(info);
  return info;
}

/** Install is disabled on vite dev servers — only real builds can self-update. */
export function canInstallUpdates(): boolean {
  return import.meta.env.PROD || import.meta.env.MODE === "test";
}

/**
 * How the app was installed: "nsis" (an NSIS install — the signed updater
 * can replace it in place) or "portable" (a zip the user unpacked — the
 * updater falls back to the portable package).
 */
export async function updateInstallKind(): Promise<"nsis" | "portable"> {
  try {
    const kind = await invoke<string>("update_install_kind");
    return kind === "nsis" ? "nsis" : "portable";
  } catch {
    return "portable";
  }
}

/**
 * Install a signed update in place (Tauri updater plugin).
 *
 * The plugin downloads the release artifact, verifies its signature against
 * the key baked into the binary and hands it to the installer. Only works
 * for an NSIS installation — a portable build has no installer to run.
 */
export async function installSignedUpdate(
  opts: { onProgress?: (p: DownloadProgress) => void } = {}
): Promise<{ bytes: number }> {
  const update = signedUpdate;
  if (!update) throw new Error("no signed update available");
  let received = 0;
  const total = typeof update.length === "number" ? update.length : 0;
  await update.downloadAndInstall((progress) => {
    if (progress?.event === "Progress") {
      received += progress.data?.chunkLength ?? 0;
      opts.onProgress?.({ received, total: progress.data?.contentLength ?? total });
    } else if (progress?.event === "Started") {
      opts.onProgress?.({ received: 0, total: progress.data?.contentLength ?? total });
    }
  });
  return { bytes: received || total };
}

/**
 * Ask Rust to download the portable ZIP into its temp file (GitHub release
 * assets send no CORS headers, so a webview fetch always fails). Progress
 * arrives via the `updateDownloadProgress` event; aborting the signal makes
 * Rust stop and cleans up the partial file.
 */
export async function downloadUpdate(
  info: UpdateInfo,
  opts: {
    signal?: AbortSignal;
    onProgress?: (p: DownloadProgress) => void;
  } = {}
): Promise<{ bytes: number }> {
  if (!info.zipUrl) throw new Error("release has no portable package");
  const unlisten = await listen<DownloadProgress>("updateDownloadProgress", (e) => {
    opts.onProgress?.(e.payload);
  });
  const onAbort = (): void => {
    void discardUpdate();
  };
  opts.signal?.addEventListener("abort", onAbort);
  try {
    if (opts.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const bytes = await invoke<number>("update_download_asset", {
      url: info.zipUrl,
      tag: info.latest,
    });
    return { bytes };
  } catch (err) {
    try {
      await invoke("update_discard");
    } catch {
      // ignore cleanup errors
    }
    if (opts.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    throw err instanceof Error ? err : new Error(String(err));
  } finally {
    opts.signal?.removeEventListener("abort", onAbort);
    unlisten();
  }
}

/** Hand the downloaded ZIP to Rust: write .bat, spawn it, exit the app. */
export async function applyUpdate(info: UpdateInfo): Promise<void> {
  await invoke("apply_update", { tag: info.latest });
}

/** Drop the pending download (banner cancel). */
export async function discardUpdate(): Promise<void> {
  try {
    await invoke("update_discard");
  } catch {
    // ignore
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
