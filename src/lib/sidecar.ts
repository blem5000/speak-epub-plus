/**
 * JSON-RPC sidecar spike — stdin/stdout primary, HTTP fallback documented.
 * GUI → Rust (tauri shell) → Python sidecar via core/config.py:get_venv_python()
 * Rust side should emit "python_sidecar_call" and spawn venv python.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type RpcRequest = {
  id: string;
  method: string;
  params?: unknown;
};

export type RpcResponse = {
  id: string;
  result?: unknown;
  error?: { code: string; message: string; retryable?: boolean };
};

/**
 * Send a typed event via Tauri emit → Python sidecar.
 * Rust handler "python_sidecar_call" should forward to sidecar stdin.
 */
export async function callSidecar(
  method: string,
  params?: unknown,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const payload: RpcRequest = { id, method, params };
  if (opts?.signal?.aborted) {
    return { id, error: { code: "ABORTED", message: "aborted" } };
  }

  // wire external abort signal if provided
  let externalAbortHandler: (() => void) | null = null;
  const linkAbort = (ctl: AbortController): void => {
    if (opts?.signal) {
      externalAbortHandler = (): void => ctl.abort();
      opts.signal.addEventListener("abort", externalAbortHandler, { once: true });
    }
  };
  const unlinkAbort = (ctl: AbortController): void => {
    if (externalAbortHandler && opts?.signal) {
      opts.signal.removeEventListener("abort", externalAbortHandler);
      externalAbortHandler = null;
    }
    void ctl;
  };

  // P10: ensure abort listeners are always removed (no leak)
  let primaryAbortHandler: (() => void) | null = null;
  try {
    if (opts?.signal?.aborted) throw new Error("aborted");
    // Primary: stdin/stdout via Rust shell plugin — with race against abort
    const invokePromise = invoke<RpcResponse>("python_sidecar_call", {
      payload,
    });
    if (opts?.signal) {
      const abortPromise = new Promise<never>((_, reject) => {
        primaryAbortHandler = (): void => reject(new Error("aborted"));
        opts.signal!.addEventListener("abort", primaryAbortHandler, { once: true });
      });
      try {
        const result = (await Promise.race([invokePromise, abortPromise])) as RpcResponse;
        return result;
      } finally {
        if (primaryAbortHandler && opts.signal) {
          opts.signal.removeEventListener("abort", primaryAbortHandler);
          primaryAbortHandler = null;
        }
      }
    }
    const result = await invokePromise;
    return result;
  } catch (err) {
    // cleanup primary abort handler on throw
    if (primaryAbortHandler && opts?.signal) {
      opts.signal.removeEventListener("abort", primaryAbortHandler);
      primaryAbortHandler = null;
    }
    // Fallback documented in docs/sidecar-fallback.md — keep app open, show toast
    const msg = err instanceof Error ? err.message : String(err);
    if (msg === "aborted" || opts?.signal?.aborted) {
      return { id, error: { code: "ABORTED", message: "aborted" } };
    }
    console.warn(`sidecar failed: ${msg} — falling back to http://localhost:17381`, err);
    // Attempt HTTP fallback (best-effort) with timeout and id check
    const ctl = new AbortController();
    let t: number | null = null;
    try {
      linkAbort(ctl);
      t = (typeof window !== "undefined" ? window.setTimeout : setTimeout)(() => ctl.abort(), 2000) as unknown as number;
      // if external signal already aborted, abort immediately
      if (opts?.signal?.aborted) ctl.abort();
      const res = await fetch("http://localhost:17381/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctl.signal,
      });
      if (!res.ok) throw new Error(`http ${res.status}`);
      const json = (await res.json()) as RpcResponse;
      if (json.id !== id) throw new Error(`id mismatch ${json.id} != ${id}`);
      return json;
    } catch (httpErr) {
      const httpMsg = httpErr instanceof Error ? httpErr.message : String(httpErr);
      return {
        id,
        error: {
          code: "SIDECAR_FAILED",
          message: `sidecar failed: ${msg} fallback http also failed: ${httpMsg}`,
        },
      };
    } finally {
      if (t !== null) clearTimeout(t);
      unlinkAbort(ctl);
    }
  }
}

export async function ping(): Promise<boolean> {
  const res = await callSidecar("ping");
  return (res.result as { pong?: boolean })?.pong === true || res.result === "pong";
}

// Event bus types per AD-6 — single typed bus, no polling
export type ChapterStatusEvent = {
  chapter: number;
  status: "queued" | "fetching" | "cleaning" | "done" | "error";
};
export type PartStatusEvent = {
  chapter_number: number;
  part_number: number;
  part_count: number;
  is_final_chapter_file: boolean;
  status: string;
};
export type LogLineEvent = { line: string };
export type ThrottleChangedEvent = { tier: string; delay: number };

// Fetch Chapter(s) types — Core→Port→Adapter AD-1, politeness AD-3, cache AD-9
export type FetchChapterParams = { url: string };
export type FetchChaptersParams = {
  urls?: string[];
  novelUrl?: string;
  novel_url?: string;
  from?: number | null;
  to?: number | null;
};
export type FetchResult = {
  url: string;
  title: string;
  html: string;
  text: string;
  cover_url?: string | null;
};
export type FetchChaptersResult = {
  chapters: FetchResult[];
  skipped: number;
  total: number;
  badge?: string | null;
  logs?: string[];
  throttles?: ThrottleChangedEvent[];
};

export async function onChapterStatus(
  cb: (payload: ChapterStatusEvent) => void
): Promise<UnlistenFn> {
  return listen<ChapterStatusEvent>("chapterStatus", (e) => cb(e.payload));
}
export async function onPartStatus(
  cb: (payload: PartStatusEvent) => void
): Promise<UnlistenFn> {
  return listen<PartStatusEvent>("partStatus", (e) => cb(e.payload));
}
export async function onLogLine(
  cb: (payload: LogLineEvent) => void
): Promise<UnlistenFn> {
  return listen<LogLineEvent>("logLine", (e) => cb(e.payload));
}
export async function onThrottleChanged(
  cb: (payload: ThrottleChangedEvent) => void
): Promise<UnlistenFn> {
  return listen<ThrottleChangedEvent>("throttleChanged", (e) => cb(e.payload));
}

// Fetch helpers — no new transport, reuse callSidecar AD-4/6 (sidecar.ts:25)
export async function fetchChapter(
  url: string,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  return callSidecar("fetchChapter", { url }, opts);
}

export async function fetchChapters(
  params: FetchChaptersParams,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  // normalize camel/snake + trim + guard
  if (params.urls && params.urls.length > 1000) throw new Error("too many urls");
  const payload: Record<string, unknown> = {};
  if (params.urls) payload.urls = params.urls.map((u) => u.trim()).filter(Boolean);
  if (params.novelUrl) payload.novelUrl = params.novelUrl.trim();
  if (params.novel_url) payload.novelUrl = params.novel_url.trim();
  if (params.from !== undefined) payload.from = params.from;
  if (params.to !== undefined) payload.to = params.to;
  return callSidecar("fetchChapters", payload, opts);
}

export async function getCacheStatus(
  params: FetchChaptersParams,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const payload: Record<string, unknown> = {};
  if (params.urls) payload.urls = params.urls.map((u) => u.trim()).filter(Boolean);
  if (params.novelUrl) payload.novelUrl = params.novelUrl.trim();
  if (params.novel_url) payload.novel_url = params.novel_url.trim();
  if (params.from !== undefined) payload.from = params.from;
  if (params.to !== undefined) payload.to = params.to;
  return callSidecar("getCacheStatus", payload, opts);
}

// Preview & selector boundary — AD-7 Story 2.2
export type PreviewParams = { url: string; start?: string | null; end?: string | null };
export type PreviewResult = {
  url: string;
  originalHtml: string;
  originalText: string;
  html: string;
  text: string;
  filteredHtml?: string;
  filteredText?: string;
  removedCount?: number;
  filters?: FilterItem[];
  start: string | null;
  end: string | null;
};
export type SelectorsResult = {
  site: string;
  start: string | null;
  end: string | null;
  defaultStart: string | null;
  defaultEnd: string | null;
  override: { start: string | null; end: string | null } | null;
};

export async function previewChapter(
  params: PreviewParams,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  if (!params.url || !params.url.trim()) throw new Error("url must be non-empty");
  const payload: Record<string, unknown> = { url: params.url.trim() };
  if (params.start !== undefined) payload.start = params.start?.trim() ?? null;
  if (params.end !== undefined) payload.end = params.end?.trim() ?? null;
  return callSidecar("previewChapter", payload, opts);
}

export async function getSelectors(
  params: { url?: string; site?: string },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const payload: Record<string, unknown> = {};
  if (params.url) payload.url = params.url.trim();
  if (params.site) payload.site = params.site.trim().toLowerCase().replace(/\/$/, "");
  return callSidecar("getSelectors", payload, opts);
}

export async function saveSelectors(
  params: { url?: string; site?: string; start: string | null; end: string | null },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const payload: Record<string, unknown> = {};
  if (params.url) payload.url = params.url.trim();
  if (params.site) payload.site = params.site.trim();
  if (params.start !== undefined) payload.start = params.start?.trim() ?? null;
  if (params.end !== undefined) payload.end = params.end?.trim() ?? null;
  return callSidecar("saveSelectors", payload, opts);
}

export async function clearSelectors(
  params: { url?: string; site?: string },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const payload: Record<string, unknown> = {};
  if (params.url) payload.url = params.url.trim();
  if (params.site) payload.site = params.site.trim();
  return callSidecar("clearSelectors", payload, opts);
}

// Filters — plain+regex AD-2 Story 2.3
export type FilterItem = { pattern: string; isRegex: boolean };
export type FiltersResult = { filters: FilterItem[] };

export async function getFilters(opts?: { signal?: AbortSignal }): Promise<RpcResponse> {
  return callSidecar("getFilters", {}, opts);
}

export async function addFilter(
  params: { pattern: string; isRegex: boolean },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const pat = params.pattern?.trim();
  if (!pat) throw new Error("pattern must be non-empty");
  if (pat.length > 200) throw new Error("pattern too long");
  if (params.isRegex) {
    try {
      new RegExp(pat);
    } catch {
      throw new Error(`invalid regex: ${pat}`);
    }
  }
  return callSidecar("addFilter", { pattern: pat, isRegex: params.isRegex }, opts);
}

export async function removeFilter(
  params: { index: number } | { pattern: string; isRegex?: boolean },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const payload: Record<string, unknown> = {};
  if ("index" in params) payload.index = (params as { index: number }).index;
  if ("pattern" in params) payload.pattern = (params as { pattern: string }).pattern.trim();
  if ("isRegex" in params) payload.isRegex = (params as { isRegex?: boolean }).isRegex;
  return callSidecar("removeFilter", payload, opts);
}

export async function saveFilters(
  params: { filters: FilterItem[] },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  if (params.filters.length > 100) throw new Error("too many filters");
  const sanitized = params.filters.map((f) => ({
    pattern: f.pattern.trim(),
    isRegex: !!f.isRegex,
  }));
  for (const f of sanitized) {
    if (!f.pattern) throw new Error("pattern must be non-empty");
    if (f.pattern.length > 200) throw new Error("pattern too long");
    if (f.isRegex) {
      try {
        new RegExp(f.pattern);
      } catch {
        throw new Error(`invalid regex: ${f.pattern}`);
      }
    }
  }
  return callSidecar("saveFilters", { filters: sanitized }, opts);
}

// EPUB — Story 2.4 buildEpub gate
export type EpubParams = {
  novelUrl: string;
  from?: number | null;
  to?: number | null;
  title?: string | null;
  author?: string | null;
  coverUrl?: string | null;
  outputDir?: string | null;
  urls?: string[];
};
export type EpubResult = {
  path: string;
  size: number;
  chapter_count: number;
  epubcheck_ok: boolean;
  epubcheck_proxy?: boolean;
  messages: string[];
  logs?: string[];
  keepEPUB?: boolean;
  from?: number;
  to?: number;
  slug?: string;
};

export async function buildEpub(
  params: EpubParams,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  if (!params.novelUrl || !params.novelUrl.trim()) throw new Error("url must be non-empty");
  const novelUrl = params.novelUrl.trim();
  if (!/^https?:\/\//i.test(novelUrl)) throw new Error("url must be http(s)");
  // trim url/title sanitization
  const payload: Record<string, unknown> = { novelUrl };
  if (params.from !== undefined && params.from !== null) payload.from = Math.trunc(Number(params.from));
  if (params.to !== undefined && params.to !== null) payload.to = Math.trunc(Number(params.to));
  if (params.title !== undefined && params.title !== null) {
    const t = String(params.title).trim();
    payload.title = t.slice(0, 200);
  }
  if (params.author !== undefined && params.author !== null) {
    const a = String(params.author).trim();
    payload.author = a.slice(0, 200);
  }
  if (params.coverUrl !== undefined && params.coverUrl !== null) {
    const c = String(params.coverUrl).trim();
    if (c) payload.coverUrl = c.slice(0, 500);
  }
  if (params.outputDir) {
    const od = String(params.outputDir).trim();
    if (od.includes("..") || od.includes("\0")) throw new Error("outputDir invalid");
    payload.outputDir = od;
  }
  if (params.urls) {
    if (!Array.isArray(params.urls)) throw new Error("urls must be array");
    if (params.urls.length > 1000) throw new Error("too many urls");
    if (!params.urls.every((u) => typeof u === "string")) throw new Error("urls must be strings");
    const cleaned = params.urls.map((u) => u.trim()).filter(Boolean);
    if (cleaned.length === 0) throw new Error("urls empty after trim");
    payload.urls = cleaned;
  }
  return callSidecar("buildEpub", payload, opts);
}

export async function getEpubStatus(
  params: { novelUrl?: string; from?: number; to?: number; outputDir?: string },
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  return callSidecar("getEpubStatus", params, opts);
}

// Audiobook — Step 7: MP3/M4A/M4B via core/audio.py build_audio gate
export type AudioParams = {
  novelUrl: string;
  from?: number | null;
  to?: number | null;
  title?: string | null;
  urls?: string[];
  voice?: string;
  parallel?: number;
  retries?: number;
  chunkSize?: number;
  format?: string;
};
export type AudioChapter = { number: number; title: string; path: string };
export type AudioResult = {
  audio_dir: string;
  chapter_count: number;
  part_count: number;
  chapters: AudioChapter[];
  audiobook: { path: string; size: number; format: string } | null;
  format: string;
  voice: string;
  ffmpeg: boolean;
  logs?: string[];
  from?: number;
  to?: number;
  slug?: string;
};

export async function buildAudio(params: AudioParams, opts?: { signal?: AbortSignal }): Promise<RpcResponse> {
  if (!params.novelUrl || !params.novelUrl.trim()) throw new Error("url must be non-empty");
  const novelUrl = params.novelUrl.trim();
  if (!/^https?:\/\//i.test(novelUrl)) throw new Error("url must be http(s)");
  const payload: Record<string, unknown> = { novelUrl };
  if (params.from !== undefined && params.from !== null) payload.from = Math.trunc(Number(params.from));
  if (params.to !== undefined && params.to !== null) payload.to = Math.trunc(Number(params.to));
  if (params.title !== undefined && params.title !== null) {
    payload.title = String(params.title).trim().slice(0, 200);
  }
  if (params.urls) {
    if (!Array.isArray(params.urls)) throw new Error("urls must be array");
    if (params.urls.length > 1000) throw new Error("too many urls");
    if (!params.urls.every((u) => typeof u === "string")) throw new Error("urls must be strings");
    const cleaned = params.urls.map((u) => u.trim()).filter(Boolean);
    if (cleaned.length === 0) throw new Error("urls empty after trim");
    payload.urls = cleaned;
  }
  if (params.voice !== undefined && params.voice !== null) {
    const v = String(params.voice).trim();
    if (!v) throw new Error("voice must be non-empty");
    payload.voice = v.slice(0, 100);
  }
  if (params.parallel !== undefined && params.parallel !== null) payload.parallel = Math.trunc(Number(params.parallel));
  if (params.retries !== undefined && params.retries !== null) payload.retries = Math.trunc(Number(params.retries));
  if (params.chunkSize !== undefined && params.chunkSize !== null)
    payload.chunkSize = Math.trunc(Number(params.chunkSize));
  if (params.format !== undefined && params.format !== null) {
    const f = String(params.format).trim().toLowerCase();
    if (f !== "mp3" && f !== "m4b" && f !== "m4a") throw new Error("format must be mp3, m4b or m4a");
    payload.format = f;
  }
  return callSidecar("buildAudio", payload, opts);
}

/** Open a file/folder via Tauri opener, with browser fallback. Shared by Result/Audiobook. */
export async function openPath(path: string): Promise<void> {
  if (!path || !path.trim()) return;
  const p = path.trim();
  try {
    await invoke("plugin:opener|open_path", { path: p });
    return;
  } catch {
    try {
      await invoke("plugin:shell|open", { path: p });
      return;
    } catch {
      try {
        window.open(`file://${p}`, "_blank");
      } catch {}
    }
  }
}

/** Reveal a file (or folder) in the system file manager. Best UX for "Open folder". */
export async function revealPath(path: string): Promise<void> {
  if (!path || !path.trim()) return;
  await invoke("plugin:opener|reveal_item_in_dir", { paths: [path.trim()] });
}

/**
 * Settings store helpers — mirrors `core/config.py:DEFAULT_STORE` via JSON-RPC.
 * AD-10 single source `store.json` via `core/config.py:load_store`/`save_store`.
 * Use `getStore` on mount to prefill Settings form, `setStore` on blur to persist.
 *
 * Valid patch keys (canonical, kebab/snake normalized by Core):
 * - `voice` string ≤100 trimmed (e.g. "pl-PL-ZofiaNeural")
 * - `rate` string pattern `^[+-]?\d+%$` clamped -100..+100 with `%` (e.g. "+0%")
 * - `parallel` int 1-6 (UI shows 2-3, clamped 1-6)
 * - `chunk-size` / `chunk_size` int 500-5000
 * - `retries` int 1-10
 * - `scrapeDelay` / `scrape_delay` int 0-20000 (preset 3000/4000/5000/custom)
 * - `safeMode` / `safe_mode` bool
 * - `keepEPUB` / `keepMP3` / `keepM4B` bool
 * Persist via atomic `.tmp` replace — no polling, no direct frontend file write.
 */
export async function getStore(opts?: { signal?: AbortSignal }): Promise<RpcResponse> {
  return callSidecar("getStore", {}, opts);
}

export async function setStore(
  patch: Record<string, unknown>,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  return callSidecar("setStore", patch, opts);
}

// Type guards for fetchChapter(s) responses — strict shape
export function isFetchChapterResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return typeof r.html === "string" && typeof r.url === "string" && "text" in r;
}
export function isFetchChaptersResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return Array.isArray(r.chapters) && typeof r.total === "number" && typeof r.skipped === "number";
}
export function isPreviewResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return typeof r.html === "string" && typeof r.text === "string" && typeof r.originalHtml === "string";
}
export function isSelectorsResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return typeof r.site === "string" && "start" in r && "end" in r;
}
export function isFiltersResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return Array.isArray(r.filters);
}
export function isEpubResult(res: RpcResponse): boolean {  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  const hasPath = typeof r.path === "string";
  const hasSize = typeof r.size === "number";
  const hasEpubCheck =
    typeof r.epubcheck_ok === "boolean" ||
    typeof (r as Record<string, unknown>).epubcheckOk === "boolean";
  const hasCount =
    typeof (r as Record<string, unknown>).chapter_count === "number" ||
    typeof (r as Record<string, unknown>).chapterCount === "number";
  const hasMessages = Array.isArray(r.messages);
  return hasPath && hasSize && hasEpubCheck && hasCount && hasMessages;
}
export function isAudioResult(res: RpcResponse): boolean {
  if (!res.result || typeof res.result !== "object") return false;
  const r = res.result as Record<string, unknown>;
  return (
    typeof r.audio_dir === "string" &&
    typeof r.chapter_count === "number" &&
    Array.isArray(r.chapters) &&
    typeof r.format === "string"
  );
}
