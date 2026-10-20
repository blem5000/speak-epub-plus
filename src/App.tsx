import { useEffect, useRef, useState, useCallback } from "react";
import { t, getLocale, setLocale } from "./i18n";
import { buildEpub, callSidecar, cancelSidecarJob, getStore, isEpubResult, setStore, type EpubResult } from "./lib/sidecar";
import QueuePanel, { type QueueItem, type QueueOutcome } from "./components/QueuePanel";
import FindInput from "./components/FindInput";
import ResultsTable from "./components/ResultsTable";
import ChapterList from "./components/ChapterList";
import Preview from "./components/Preview";
import Filters from "./components/Filters";
import Result from "./components/Result";
import Audiobook, { type AudioFormat, type AudiobookHandle } from "./components/Audiobook";
import UpdaterBanner from "./components/UpdaterBanner";
import RuntimeBanner from "./components/RuntimeBanner";
import Queue from "./components/Queue";
import ThrottleBadge from "./components/ThrottleBadge";
import ProgressTrack from "./components/ProgressTrack";
import Settings from "./components/Settings";
import RangeBar from "./components/RangeBar";
import { useChapterList } from "./hooks/useChapterList";
import { useDebouncedSearch } from "./hooks/useDebouncedSearch";
import { useFetcher } from "./hooks/useFetcher";
import { useGlobalKeys } from "./hooks/useGlobalKeys";
import { selectedUrlsForFetch as urlsForFetch } from "./lib/selection";

export default function App(): JSX.Element {
  const [locale, setLocaleState] = useState(getLocale());
  const [query, setQuery] = useState("");
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const ctaRef = useRef<HTMLButtonElement>(null);
  const { searching, results, error } = useDebouncedSearch(query, 400);

  // Chapter List state — GUI thin, Core owns persistence via getSelection/setSelection (D2/D3)
  const { loading: chapterLoading, list: chapterList, error: chapterError, cover: chapterCover } = useChapterList(selectedUrl);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [from, setFrom] = useState<number>(1);
  const [to, setTo] = useState<number>(30);
  const [anchor, setAnchor] = useState<number | null>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const retryTimeoutRef = useRef<number | null>(null);
  const skipNextClearRef = useRef(false);

  // Load persisted selection from Core on mount (D3 + P6 fix) — with unmount guard + url restore
  useEffect(() => {
    let alive = true;
    callSidecar("getSelection", {})
      .then((res) => {
        if (!alive) return;
        const r = res as { result?: { selection?: number[]; from?: number; to?: number; url?: string | null } };
        if (r?.result?.selection && Array.isArray(r.result.selection)) {
          const arr = r.result.selection.filter((n) => Number.isInteger(n) && n >= 1);
          if (arr.length > 0) setSelected(new Set(arr));
          if (Number.isFinite(r.result.from as number)) setFrom(Number(r.result.from));
          if (Number.isFinite(r.result.to as number)) setTo(Number(r.result.to));
        }
        // P6: restore persisted url to selectedUrl so Wybrano visible after reload (case-insensitive)
        // mark to skip next wipe so restored selection/from/to not cleared
        if (r?.result?.url && typeof r.result.url === "string" && r.result.url.trim().toLowerCase().startsWith("http")) {
          skipNextClearRef.current = true;
          setSelectedUrl(r.result.url.trim());
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Restore persisted UI locale + outputDir from Core on mount ("" = auto-detect)
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await getStore();
        if (!alive) return;
        const result = res?.result as Record<string, unknown> | undefined;
        const saved = result?.locale;
        if (saved === "en" || saved === "pl") {
          setLocale(saved);
          setLocaleState(saved);
        }
        const savedDir = result?.outputDir;
        if (typeof savedDir === "string" && savedDir.trim()) setOutputDir(savedDir.trim());
      } catch {
        // silent — falls back to system detection
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Persist selection to Core on change (D2/D3 + P8 retry)
  useEffect(() => {
    const selArray = Array.from(selected);
    // fire-and-forget, debounce 300ms with one retry on failure
    const id = window.setTimeout(() => {
      callSidecar("setSelection", { selection: selArray, from, to, url: selectedUrl }).catch(() => {
        // retry once after 1s for offline/transient failure
        window.setTimeout(() => {
          callSidecar("setSelection", { selection: selArray, from, to, url: selectedUrl }).catch(() => {
            if (import.meta.env.DEV) console.warn("setSelection failed after retry");
          });
        }, 1000);
      });
    }, 300);
    return () => window.clearTimeout(id);
  }, [selected, from, to, selectedUrl]);

  // focus CTA when no-results appears for a11y — guard error to avoid focus jump on toast
  useEffect(() => {
    const trimmed = query.trim();
    if (error) return;
    if (!searching && trimmed && results.length === 0) {
      // delay to let DOM mount
      const id = window.setTimeout(() => ctaRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [searching, results.length, query, error]);

  // reset stale selection when results change (new search)
  useEffect(() => {
    if (selectedUrl && !results.some((r) => r.url === selectedUrl)) {
      setSelectedUrl(null);
    }
  }, [results, selectedUrl]);

  // auto-select when the search yields exactly one site — no click needed
  useEffect(() => {
    if (results.length !== 1) return;
    const only = results[0]?.url;
    if (only && selectedUrl !== only) {
      setSelectedUrl(only);
    }
  }, [results, selectedUrl]);

  // reset selection when selectedUrl changes (FR1→FR2 discovery standalone demo)
  useEffect(() => {
    if (skipNextClearRef.current) {
      skipNextClearRef.current = false;
      return;
    }
    setSelected(new Set());
    setAnchor(null);
    setFrom(1);
    setTo(30);
  }, [selectedUrl]);

  // clamp from/to when chapter list loads or N changes + prune selection out-of-range
  // Only trigger on length/loading change to avoid loop from selected dep
  useEffect(() => {
    const N = chapterList.length;
    if (N > 0) {
      // clamp from/to without depending on selected
      setFrom((prevFrom) => {
        let a = prevFrom;
        if (!Number.isFinite(a)) a = 1;
        a = Math.trunc(a);
        if (a < 1) a = 1;
        if (a > N) a = N;
        return a;
      });
      setTo((prevTo) => {
        let b = prevTo;
        if (!Number.isFinite(b)) b = 1;
        b = Math.trunc(b);
        if (b < 1) b = 1;
        if (b > N) b = N;
        return b;
      });
      // prune selected indices that are now out-of-range
      setSelected((prev) => {
        const filtered = Array.from(prev).filter((n) => Number.isInteger(n) && n >= 1 && n <= N);
        if (filtered.length !== prev.size) return new Set(filtered);
        return prev;
      });
      setAnchor((prev) => {
        if (prev != null && (prev < 1 || prev > N || !Number.isInteger(prev))) return null;
        return prev;
      });
    } else if (!chapterLoading) {
      // only clear when not loading (avoid wiping persist during skeleton)
      setSelected((prev) => (prev.size > 0 ? new Set() : prev));
      setAnchor((prev) => (prev != null ? null : prev));
    }
  }, [chapterList.length, chapterLoading]);

  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current && typeof window !== "undefined") window.clearTimeout(retryTimeoutRef.current);
    };
  }, []);

  const toggleLocale = (): void => {
    const next = locale === "en" ? "pl" : "en";
    setLocale(next);
    setLocaleState(next);
    // best-effort persist with one retry (P8 pattern) — UI never waits on the store
    const persistLocale = (): Promise<unknown> => setStore({ locale: next });
    try {
      void persistLocale().catch(() => {
        window.setTimeout(() => {
          void persistLocale().catch(() => {
            if (import.meta.env.DEV) console.warn("setLocale persist failed after retry");
          });
        }, 1000);
      });
    } catch {
      // sidecar unavailable (tests/dev)
    }
  };

  const trimmedQuery = query.trim();
  const showNoResults = !searching && trimmedQuery.length > 0 && results.length === 0;

  const handleRangeChange = (nextFrom: number, nextTo: number): void => {
    setFrom(nextFrom);
    setTo(nextTo);
  };

  const [previewIdx, setPreviewIdx] = useState<number | null>(null);
  const handlePreview = (idx: number): void => {
    setPreviewIdx(idx);
  };
  // Global keys: Esc closes topmost dialog first, else the app (see useGlobalKeys).
  const closeTopModal = useCallback((): boolean => {
    if (previewIdx != null) {
      setPreviewIdx(null);
      return true;
    }
    return false;
  }, [previewIdx]);
  useGlobalKeys(closeTopModal);
  const previewChapter = previewIdx != null ? chapterList.find((c) => c.index === previewIdx) ?? null : null;

  const hasSelectedUrl = !!(selectedUrl && selectedUrl.trim());
  const showChapterSkeleton = hasSelectedUrl && chapterLoading;
  const showChapterList = hasSelectedUrl && !chapterLoading && chapterList.length > 0 && !chapterError;
  const showChapterError = hasSelectedUrl && !chapterLoading && !!chapterError;
  const showChapterEmpty = hasSelectedUrl && !chapterLoading && !chapterError && chapterList.length === 0;

  // Fetcher — polite sequential, cache resume, throttle badge (Story 4.1 live)
  const {
    fetching,
    logs,
    throttle,
    statuses,
    partStatuses,
    progress,
    elapsedSec,
    badge,
    error: fetcherError,
    start: startFetcher,
    abort: abortFetcher,
    appendLogs,
    setStatuses,
    setPartStatuses,
  } = useFetcher();
  const N = chapterList.length;

  // EPUB Result — Story 2.4
  const [epubResult, setEpubResult] = useState<EpubResult | null>(null);
  const [epubBuilding, setEpubBuilding] = useState(false);
  const [epubError, setEpubError] = useState<string | null>(null);
  const [epubMissing, setEpubMissing] = useState<string[] | null>(null);
  // Audiobook build (Step 7) — shares the fetcher event bus for part progress
  const [audioBuilding, setAudioBuilding] = useState(false);
  // Wizard (single Start = fetch → build selected targets)
  const [epubWanted, setEpubWanted] = useState(true);
  const [audioWanted, setAudioWanted] = useState(true);
  const [audioFormat, setAudioFormat] = useState<AudioFormat>("m4b");
  const [outputDir, setOutputDir] = useState<string>("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [epubTouched, setEpubTouched] = useState(false);
  const [audioTouched, setAudioTouched] = useState(false);
  const [phase, setPhase] = useState<"idle" | "fetching" | "epub" | "audio">("idle");
  const [pickerToast, setPickerToast] = useState<string | null>(null);
  // Batch queue — several novels converted one after another
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [queueOutcomes, setQueueOutcomes] = useState<QueueOutcome[]>([]);
  const [queueRunning, setQueueRunning] = useState(false);
  const [queueProgress, setQueueProgress] = useState<{ index: number; total: number; title: string } | null>(null);
  const audiobookRef = useRef<AudiobookHandle>(null);
  const epubAbortRef = useRef<AbortController | null>(null);
  const epubStopRef = useRef(false);
  const logPaneRef = useRef<HTMLDivElement>(null);
  // One job at a time: fetch → epub → audio (wizard orchestration)
  const jobRunning = fetching || epubBuilding || audioBuilding;

  // auto-scroll log pane when logs change (reuse queue logic) — preserve for Result pane, Queue handles its own
  useEffect(() => {
    if (logPaneRef.current) {
      logPaneRef.current.scrollTop = logPaneRef.current.scrollHeight;
    }
  }, [logs]);
  const selectedUrlsForFetch = (() => {
    // Shared helper (positional from–to, see lib/selection): checkbox
    // selection wins, else the range — never silently empty for sparse lists.
    return urlsForFetch(chapterList, selected, from, to);
  })();
  const handleStartFetchRange = (rangeFrom: number, rangeTo: number): void => {
    // Single Start entry: fetch exactly the committed od–do range.
    // URLs are computed from the explicit args (never stale state).
    if (!hasSelectedUrl || chapterLoading || N === 0 || fetching || audioBuilding) return;
    const urls = urlsForFetch(chapterList, new Set(), rangeFrom, rangeTo);
    if (urls.length === 0) return;
    const clampOne = (v: number, fallback: number): number =>
      Number.isFinite(v) ? Math.max(1, Math.min(Math.trunc(v), N)) : fallback;
    void startFetcher({
      urls,
      novelUrl: selectedUrl ?? undefined,
      from: clampOne(rangeFrom, 1),
      to: clampOne(rangeTo, N),
    });
  };

  // Native folder picker (tauri-plugin-dialog) — persisted as store.outputDir
  const handlePickFolder = async (): Promise<void> => {
    try {
      const mod = await import("@tauri-apps/plugin-dialog");
      const picked = await mod.open({
        directory: true,
        multiple: false,
        title: t("wizard.pickFolder") as string,
        defaultPath: outputDir || undefined,
      });
      if (typeof picked !== "string" || !picked.trim()) return;
      const dir = picked.trim();
      setOutputDir(dir);
      void setStore({ outputDir: dir }).catch(() => {
        if (import.meta.env.DEV) console.warn("outputDir persist failed");
      });
    } catch (e) {
      setPickerToast(e instanceof Error ? e.message : String(e));
      window.setTimeout(() => setPickerToast(null), 4000);
    }
  };

  // EPUB build — Story 2.4
  const selectedResult = results.find((r) => r.url === selectedUrl) ?? null;
  const buildTitle = selectedResult?.title ?? chapterList[0]?.title ?? "book";
  const buildAuthor = (selectedResult as unknown as { author?: string })?.author ?? null;
  const canBuild = !!(hasSelectedUrl && !chapterLoading && N > 0 && !jobRunning);

  const handleBuildEpub = useCallback(
    async (urlsOverride?: string[], loOverride?: number, hiOverride?: number): Promise<boolean> => {
      const urls = urlsOverride ?? selectedUrlsForFetch;
      if (urls.length === 0) return false;
      if (!hasSelectedUrl || chapterLoading || N === 0) return false;
      if (!urlsOverride && jobRunning) return false;
      setEpubTouched(true);
      setEpubBuilding(true);
      setEpubError(null);
      setEpubMissing(null);
      epubStopRef.current = false;
      const controller = new AbortController();
      epubAbortRef.current = controller;
      // mark cleaning for each chapter in range
      const fromC = Math.max(1, Math.min(loOverride ?? from, N));
      const toC = Math.max(1, Math.min(hiOverride ?? to, N));
      const lo = Math.min(fromC, toC);
      const hi = Math.max(fromC, toC);
      // set all in range to cleaning — only existing indices
      setStatuses((prev) => {
        const next = { ...prev };
        const existing = new Set(chapterList.map((c) => c.index));
        for (let i = lo; i <= hi; i++) {
          if (!existing.has(i)) continue;
          if (urls.some((u) => chapterList.find((c) => c.url === u && c.index === i))) {
            next[i] = "cleaning";
          } else if (selected.size === 0) {
            next[i] = "cleaning";
          }
        }
        return next;
      });
      appendLogs([`building epub ${lo}->${hi}`, `cleaning chapter ${lo}`]);
      try {
        const res = await buildEpub(
          {
            novelUrl: selectedUrl ?? "",
            from: lo,
            to: hi,
            title: buildTitle,
            author: buildAuthor ?? undefined,
            coverUrl: chapterCover ?? undefined,
            urls,
            outputDir: outputDir || undefined,
          },
          { signal: controller.signal }
        );
        if (res.error) {
          const code = res.error.code;
          const msg = res.error.message;
          // User pressed Stop — detached UI, backend process killed. Not an error.
          if (code === "ABORTED" || epubStopRef.current) return false;
          if (code === "CACHE_MISS") {
            const missing = (res.error as unknown as { missing?: string[] }).missing ?? [];
            setEpubMissing(missing);
            setEpubError(`CACHE_MISS: ${msg}`);
            const missLogs = missing.length > 0 ? missing.map((m) => `cache miss ${m}`) : [`cache miss ${msg}`];
            appendLogs([...missLogs, `CACHE_MISS ${msg}`]);
            // mark missing as error with per-chapter granularity
            setStatuses((prev) => {
              const next = { ...prev };
              const urlToIdx = new Map<string, number>();
              for (const ch of chapterList) urlToIdx.set(ch.url, ch.index);
              let anyMatched = false;
              for (const mu of missing) {
                const idx = urlToIdx.get(mu);
                if (idx !== undefined && next[idx] === "cleaning") {
                  next[idx] = "error";
                  anyMatched = true;
                }
              }
              if (!anyMatched) {
                for (let i = lo; i <= hi; i++) {
                  if (next[i] === "cleaning") next[i] = "error";
                }
              }
              return next;
            });
            return false;
          } else if (code === "VALUE_ERROR") {
            setEpubError(`VALUE_ERROR: ${msg}`);
            appendLogs([`VALUE_ERROR ${msg}`]);
            return false;
          } else {
            setEpubError(`${code}: ${msg}`);
            appendLogs([`error ${code}: ${msg}`]);
            return false;
          }
        }
        if (isEpubResult(res)) {
          const data = res.result as unknown as EpubResult;
          setEpubResult(data);
          setEpubError(null);
          // map cleaning->done for built range — only existing
          setStatuses((prev) => {
            const next = { ...prev };
            const existing = new Set(chapterList.map((c) => c.index));
            for (let i = lo; i <= hi; i++) {
              if (!existing.has(i)) continue;
              next[i] = "done";
            }
            return next;
          });
          const logLines = (data.logs as string[] | undefined) ?? [];
          if (logLines.length > 0) appendLogs(logLines);
          else appendLogs([`epub built ${data.path}`, `epubcheck ${data.epubcheck_ok ? "✓" : "✗"}`]);
          // also log epubcheck
          if (Array.isArray(data.messages) && data.messages.length > 0) {
            appendLogs(data.messages.map((m) => `epubcheck ${m}`));
          }
          return true;
        }
        setEpubError("unknown epub result");
        return false;
      } catch (e) {
        if (epubStopRef.current) return false;
        const msg = e instanceof Error ? e.message : String(e);
        setEpubError(msg);
        appendLogs([`epub error ${msg}`]);
        return false;
      } finally {
        epubStopRef.current = false;
        epubAbortRef.current = null;
        setEpubBuilding(false);
      }
    },
    [hasSelectedUrl, chapterLoading, N, jobRunning, selectedUrl, from, to, buildTitle, buildAuthor, chapterCover, selectedUrlsForFetch, chapterList, selected.size, appendLogs, setStatuses, outputDir]
  );

  // Wizard orchestrator — one Start: fetch → EPUB (if wanted) → audio (if wanted)
  const handleStartJob = async (rangeFrom?: number, rangeTo?: number): Promise<void> => {
    if (!hasSelectedUrl || chapterLoading || N === 0 || jobRunning) return;
    if (!epubWanted && !audioWanted) return;
    const rf = rangeFrom ?? from;
    const rt = rangeTo ?? to;
    const urls = urlsForFetch(chapterList, selected, rf, rt);
    if (urls.length === 0) return;
    const clampOne = (v: number, fallback: number): number =>
      Number.isFinite(v) ? Math.max(1, Math.min(Math.trunc(v), N)) : fallback;
    const lo = clampOne(rf, 1);
    const hi = clampOne(rt, N);
    // Mount the Audiobook section early so its imperative ref exists by the
    // time the audio phase starts (it is the builder for audio results).
    if (audioWanted) setAudioTouched(true);
    setPhase("fetching");
    const okFetch = await startFetcher({ urls, novelUrl: selectedUrl ?? undefined, from: lo, to: hi });
    if (!okFetch) {
      setPhase("idle");
      return;
    }
    if (epubWanted) {
      setPhase("epub");
      const okEpub = await handleBuildEpub(urls, lo, hi);
      if (!okEpub) {
        setPhase("idle");
        return;
      }
    }
    if (audioWanted) {
      setPhase("audio");
      // one macrotask so React flushes pending renders — the imperative ref
      // must point at a render where fetching/epubBuilding are already false
      await new Promise((resolve) => window.setTimeout(resolve, 0));
      await audiobookRef.current?.start(audioFormat);
    }
    setPhase("idle");
  };

  const handleStopAll = (): void => {
    if (fetching) abortFetcher();
    if (epubBuilding || epubAbortRef.current) {
      epubStopRef.current = true;
      epubAbortRef.current?.abort();
      epubAbortRef.current = null;
    }
    audiobookRef.current?.stop();
    // belt & braces — kill every cancelable sidecar job (fetch/epub/audio)
    void cancelSidecarJob();
    setPhase("idle");
  };

  /** Add a novel to the batch queue (from the search results). */
  const handleQueueAdd = useCallback((item: QueueItem): void => {
    setQueue((prev) => (prev.some((p) => p.url === item.url) ? prev : [...prev, item]));
  }, []);

  const handleQueueRemove = useCallback((url: string): void => {
    setQueue((prev) => prev.filter((p) => p.url !== url));
    setQueueOutcomes((prev) => prev.filter((o) => o.url !== url));
  }, []);

  const handleQueueClear = useCallback((): void => {
    setQueue([]);
    setQueueOutcomes([]);
    setQueueProgress(null);
  }, []);

  /**
   * Convert every queued novel, one after another: list the chapters,
   * fetch them into the cache, then build the audiobook. A failing book is
   * recorded and the queue continues with the next one.
   */
  const handleQueueConvert = async (): Promise<void> => {
    if (queueRunning || queue.length === 0 || jobRunning) return;
    const items = [...queue];
    setQueueRunning(true);
    setQueueOutcomes([]);
    const outcomes: QueueOutcome[] = [];
    try {
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        setQueueProgress({ index: i + 1, total: items.length, title: item.title || item.url });
        try {
          const listRes = await callSidecar("listChapters", { url: item.url });
          if (listRes.error) throw new Error(listRes.error.message || listRes.error.code);
          const raw = listRes.result as Record<string, unknown> | null;
          const chaptersRaw = Array.isArray(raw?.chapters)
            ? (raw?.chapters as Array<Record<string, unknown>>)
            : Array.isArray(raw)
              ? (raw as Array<Record<string, unknown>>)
              : [];
          const chapters = chaptersRaw
            .map((c, idx) => ({
              index: Number(c.index ?? idx + 1) || idx + 1,
              title: String(c.title ?? c.name ?? ""),
              url: String(c.url ?? c.link ?? ""),
            }))
            .filter((c) => c.url);
          if (chapters.length === 0) throw new Error("no chapters");
          const cover = (raw?.cover_url as string) ?? item.cover ?? undefined;
          const urls = chapters.map((c) => c.url);
          const fetchRes = await callSidecar(
            "fetchChapters",
            { urls, novelUrl: item.url, from: 1, to: chapters.length },
            undefined
          );
          if (fetchRes.error) throw new Error(fetchRes.error.message || fetchRes.error.code);
          const audioRes = await callSidecar(
            "buildAudio",
            {
              novelUrl: item.url,
              from: 1,
              to: chapters.length,
              title: item.title,
              urls,
              format: audioFormat,
              outputDir: outputDir || undefined,
              coverUrl: cover ?? undefined,
            },
            undefined
          );
          if (audioRes.error) throw new Error(audioRes.error.message || audioRes.error.code);
          const audio = audioRes.result as Record<string, unknown> | null;
          const book = audio?.audiobook as { path?: string } | null;
          outcomes.push({
            url: item.url,
            title: item.title,
            status: "ok",
            path: book?.path ?? (audio?.audio_dir as string | undefined),
          });
        } catch (e) {
          outcomes.push({
            url: item.url,
            title: item.title,
            status: "error",
            message: e instanceof Error ? e.message : String(e),
          });
        }
        setQueueOutcomes([...outcomes]);
      }
    } finally {
      setQueueRunning(false);
      setQueueProgress(null);
    }
  };

  return (    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* Header */}
        <header
          data-tauri-drag-region
          className="mb-8 flex items-center justify-between"
          style={{ WebkitAppRegion: "drag" } as unknown as React.CSSProperties}
        >
          <div data-tauri-drag-region>
            <h1 className="text-display font-semibold tracking-tight">
              {t("app.title")}
            </h1>
            <p className="text-body-sm text-muted-foreground">
              {t("app.subtitle")} — {t("find.hint")}
            </p>
          </div>
          <div className="flex items-center gap-2" style={{ WebkitAppRegion: "no-drag" } as unknown as React.CSSProperties}>
            <button
              type="button"
              onClick={toggleLocale}
              className="rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted"
              aria-label="Toggle locale"
            >
              {locale.toUpperCase()}
            </button>
          </div>
        </header>
        {/* Surface announcer for screen reader — Wyszukiwanie / Lista N / Wybrano X / Kolejka D/T */}
        <div
          aria-live="polite"
          aria-atomic="true"
          className="sr-only"
          data-testid="surface-announcer"
        >
          {(() => {
            const parts: string[] = [];
            if (!hasSelectedUrl) parts.push(t("find.title") || "Wyszukiwanie");
            else parts.push(`${t("chapterList.title") || "Lista"} ${N}`);
            if (selected.size > 0) parts.push(`${t("chapterList.selected", { count: selected.size, total: N }) || `Wybrano ${selected.size} z ${N}`}`);
            else if (N > 0) parts.push(`${t("chapterList.title") || "Lista"} ${N}`);
            if (fetching || progress.total > 0) parts.push(`${t("queue.title") || "Kolejka"} ${progress.done}/${progress.total}`);
            return parts.join(" • ");
          })()}
        </div>
        {/* Throttle 429 toast */}
        {throttle && throttle.tier === "safe" ? (
          <div
            role="alert"
            aria-live="assertive"
            data-testid="throttle-toast"
            className="mb-3 rounded-md border border-warning/20 bg-warning/10 px-3 py-2 text-body-sm text-warning-foreground"
          >
            {t("toast.throttled") || "Zwolnienie — 429, zwiększam opóźnienie do 10s (safe)"}
          </div>
        ) : null}
        {/* Ban hint */}
        {(chapterError && /LIST_FAILED|ban|Przerwa|限制/i.test(chapterError)) ||
        (fetcherError && /LIST_FAILED|ban|Przerwa/i.test(fetcherError)) ? (
          <div
            role="alert"
            data-testid="ban-hint"
            className="mb-3 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive"
          >
            {t("toast.ban")}
          </div>
        ) : null}
        {/* FFmpeg missing warning */}
        {(() => {
          const logStr = (logs || []).join(" ") + " " + (epubError || "") + " " + (chapterError || "");
          const ffmpegMissing = /ffmpeg/i.test(logStr);
          return ffmpegMissing ? (
            <div
              role="alert"
              data-testid="ffmpeg-warning"
              className="mb-3 rounded-md border border-warning/20 bg-warning/10 px-3 py-2 text-body-sm text-warning-foreground"
            >
              {t("ffmpeg.missing")}
            </div>
          ) : null;
        })()}
        <UpdaterBanner />
        <RuntimeBanner />

        {/* Find surface — FindInput + ResultsTable per spec 1.3 */}
        <section className="mt-6 rounded-lg border bg-card p-6 shadow-sm">
          <h2 className="text-heading font-semibold">{t("find.title")}</h2>
          <div className="mt-4">
            <FindInput value={query} onChange={setQuery} searching={searching} />
            <p className="mt-2 text-body-sm text-muted-foreground">{t("find.hint")}</p>
          </div>

          {/* searching skeleton */}
          {searching ? (
            <div className="mt-4" aria-busy="true" aria-live="polite">
              <p className="mb-2 text-body-sm text-muted-foreground">{t("find.searching")}</p>
              <div className="overflow-hidden rounded-lg border">
                <div className="sticky top-0 border-b bg-card px-4 py-2 text-body-sm font-semibold text-muted-foreground">
                  <div className="grid grid-cols-4 gap-2">
                    <span>{t("results.headers.site")}</span>
                    <span>{t("results.headers.title")}</span>
                    <span>{t("results.headers.chapters")}</span>
                    <span>{t("results.headers.link")}</span>
                  </div>
                </div>
                <div className="divide-y">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="grid grid-cols-4 gap-2 px-4 py-3">
                      <div className="h-4 animate-pulse rounded bg-muted" />
                      <div className="h-4 animate-pulse rounded bg-muted" />
                      <div className="h-4 animate-pulse rounded bg-muted" />
                      <div className="h-4 animate-pulse rounded bg-muted" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}

          {/* results table */}
          {!searching && results.length > 0 ? (
            <div className="mt-4">
              <ResultsTable
                results={results}
                selectedUrl={selectedUrl}
                onSelect={setSelectedUrl}
                onQueue={handleQueueAdd}
                queuedUrls={queue.map((q) => q.url)}
              />
              {selectedUrl ? (
                <div className="mt-2 text-body-sm text-muted-foreground">
                  {t("results.selectedLabel")}: <span className="mono text-mono">{selectedUrl}</span>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* no-results */}
          {showNoResults ? (
            <div className="mt-4 rounded-lg border border-dashed bg-card p-6 text-center">
              <p className="text-display-sm font-semibold">{t("find.noResultsTitle", { query: trimmedQuery })}</p>
              <p className="mt-1 text-body-sm text-muted-foreground">{t("find.noResultsHint")}</p>
              <div className="mt-4 flex justify-center gap-2">
                <button
                  ref={ctaRef}
                  type="button"
                  onClick={() => {
                    // focus find input for paste; CTA per spec — use data-testid for reliability
                    const el = document.querySelector<HTMLInputElement>('[data-testid="find-input"]');
                    if (el) el.focus();
                    else document.querySelector<HTMLInputElement>('input[placeholder]')?.focus();
                  }}
                  className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("find.ctaPasteUrl")}
                </button>
                <a
                  href="https://www.novelphoenix.com"
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("find.linkFallback")}
                </a>
              </div>
            </div>
          ) : null}

          {/* Batch queue — several novels converted one after another */}
          <QueuePanel
            items={queue}
            outcomes={queueOutcomes}
            running={queueRunning}
            progress={queueProgress}
            onRemove={handleQueueRemove}
            onClear={handleQueueClear}
            onConvert={() => void handleQueueConvert()}
          />

          {/* error toast inline */}
          {error ? (
            <div
              role="alert"
              aria-live="assertive"
              className="mt-3 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive"
            >
              {t("toast.searchFailed")}: {error}
            </div>
          ) : null}

          {/* Wizard: range → targets → destination → single Start (fetch + build) */}
          {hasSelectedUrl && chapterLoading ? (
            <p className="mt-4 text-body-sm text-muted-foreground" data-testid="wizard-chapter-loading" role="status" aria-live="polite">
              {t("wizard.chapterLoading")}
            </p>
          ) : null}
          {hasSelectedUrl && !chapterLoading ? (
            <div className="mt-6 space-y-3 border-t pt-4" data-testid="wizard-options">
              <RangeBar
                from={from}
                to={to}
                total={N}
                selectedCount={selected.size}
                busy={jobRunning}
                onChangeRange={handleRangeChange}
                onStartRange={(rf, rt) => void handleStartJob(rf, rt)}
                startLabel={t("wizard.start")}
              />
              <div className="flex flex-wrap items-center gap-4 text-body-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={epubWanted}
                    onChange={(e) => setEpubWanted(e.target.checked)}
                    data-testid="wizard-want-epub"
                    className="h-4 w-4 rounded border-input"
                  />
                  <span>{t("wizard.wantEpub")}</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={audioWanted}
                    onChange={(e) => setAudioWanted(e.target.checked)}
                    data-testid="wizard-want-audio"
                    className="h-4 w-4 rounded border-input"
                  />
                  <span>{t("wizard.wantAudio")}</span>
                </label>
                {!epubWanted && !audioWanted ? (
                  <span className="text-destructive" role="alert" data-testid="wizard-no-targets">
                    {t("wizard.noTargets")}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-body-sm">
                <span className="text-muted-foreground">{t("wizard.outputLabel")}:</span>
                <span className="mono break-all text-mono" data-testid="wizard-output-dir">
                  {outputDir || t("wizard.outputDefault")}
                </span>
                <button
                  type="button"
                  data-testid="wizard-pick-folder"
                  onClick={() => void handlePickFolder()}
                  className="rounded-md border bg-card px-3 py-1 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("wizard.pickFolder")}
                </button>
              </div>
              {pickerToast ? (
                <div role="alert" className="text-body-sm text-destructive" data-testid="wizard-picker-error">
                  {pickerToast}
                </div>
              ) : null}
              {jobRunning ? (
                <div className="flex flex-wrap items-center gap-3" data-testid="wizard-progress">
                  <button
                    type="button"
                    data-testid="wizard-stop"
                    onClick={handleStopAll}
                    className="rounded-md border border-destructive/40 bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {t("wizard.stop")}
                  </button>
                  {phase !== "idle" ? (
                    <span data-testid="wizard-phase" className="text-body-sm text-muted-foreground" role="status" aria-live="polite">
                      {t(`wizard.phase.${phase}`)}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        {/* Chapter list + detail moved into the Advanced panel below */}

        {/* Fetcher Queue — AD-6 live bus, expanded per-chapter + per-part (Story 4.1) */}
        {hasSelectedUrl && !chapterLoading ? (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {fetcherError ? (
                <span className="ml-3 text-body-sm text-destructive" role="alert" data-testid="fetcher-error">
                  {fetcherError}
                </span>
              ) : null}
              {elapsedSec > 0 ? (
                <span data-testid="elapsed-global" className="text-body-sm text-muted-foreground">
                  {elapsedSec}s
                </span>
              ) : null}
              <ThrottleBadge throttle={throttle} />
              <ProgressTrack done={progress.done} total={progress.total} />
            </div>
            <div className="mt-4">
              <Queue
                chapterList={chapterList}
                statuses={statuses}
                partStatuses={partStatuses}
                progress={progress}
                throttle={throttle}
                badge={badge}
                logs={logs}
                fetching={fetching}
                elapsedSec={elapsedSec}
                onAbort={abortFetcher}
              />
            </div>
            {/* preserve logPaneRef for legacy auto-scroll test, hidden */}
            <div ref={logPaneRef} data-testid="legacy-log-pane-ref" className="hidden" aria-hidden="true" />
          </>
        ) : null}

        {/* Result — Story 2.4 EPUB assembly + epubcheck (shown once started) */}
        {epubTouched || epubBuilding || epubResult || epubError ? (
          <div className="mt-6">
            <Result
              result={epubResult}
              building={epubBuilding}
              error={epubError}
              missing={epubMissing}
              canBuild={canBuild}
              onBuild={() => void handleBuildEpub()}
              from={from}
              to={to}
            />
          </div>
        ) : null}

        {/* Audiobook — Step 7: MP3/M4B/M4A from the same fetched cache */}
        {audioTouched || audioBuilding ? (
          <div className="mt-6">
            <Audiobook
              ref={audiobookRef}
              novelUrl={selectedUrl}
              from={from}
              to={to}
              title={buildTitle}
              urls={selectedUrlsForFetch}
              canStart={!!(hasSelectedUrl && !chapterLoading && N > 0)}
              fetching={fetching || epubBuilding}
              progress={progress}
              onClearParts={() => setPartStatuses({})}
              onBuildingChange={setAudioBuilding}
              showControls={false}
              coverUrl={chapterCover ?? undefined}
              format={audioFormat}
              outputDir={outputDir}
            />
          </div>
        ) : null}

        {/* Advanced — power options behind a collapsible arrow */}
        <section
          className="mt-6 rounded-lg border bg-card shadow-sm"
          aria-label={t("wizard.advanced") as string}
          data-testid="advanced-section"
        >
          <button
            type="button"
            data-testid="advanced-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((v) => !v)}
            className="flex w-full items-center justify-between rounded-lg px-6 py-4 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span className="text-heading font-semibold">{t("wizard.advanced")}</span>
            <span aria-hidden="true" className="text-muted-foreground">
              {advancedOpen ? "▾" : "▸"}
            </span>
          </button>
          {advancedOpen ? (
            <div className="space-y-6 border-t px-6 py-4" data-testid="advanced-content">
              {/* Audiobook format (consumed by the wizard Start) */}
              <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("wizard.formatLabel") as string}>
                <span className="text-body-sm font-medium">{t("wizard.formatLabel")}:</span>
                {(["mp3", "m4b", "m4a"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    role="radio"
                    aria-checked={audioFormat === f}
                    data-testid={`wizard-format-${f}`}
                    onClick={() => setAudioFormat(f)}
                    className={`rounded-md border px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      audioFormat === f ? "border-accent bg-accent/15 text-foreground" : "bg-card"
                    }`}
                  >
                    {t(f === "mp3" ? "audio.formatMP3" : f === "m4b" ? "audio.formatM4B" : "audio.formatM4A")}
                  </button>
                ))}
              </div>

              {/* Settings form (same store keys as the modal variant) */}
              <Settings open={advancedOpen} onClose={() => {}} variant="inline" />

              {/* Filters — Story 2.3 plain+regex gate */}
              <Filters />

              {/* Chapter detail — spec 1.4 */}
              {hasSelectedUrl ? (
                <div data-testid="advanced-chapters" className="rounded-lg border bg-card p-6 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-heading font-semibold">{t("chapterList.title")}</h3>
                    {chapterCover ? (
                      <img
                        src={chapterCover}
                        alt="Cover"
                        loading="lazy"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                        }}
                        className="h-12 w-8 rounded object-cover border"
                        data-testid="chapter-cover"
                      />
                    ) : null}
                  </div>
                  {/* aria-live for selection changes */}
                  <div className="sr-only" aria-live="polite" aria-atomic="true" data-testid="selection-live">
                    {t("chapterList.selected", { count: selected.size, total: chapterList.length })}
                  </div>

                  {/* loading skeleton 6 rows */}
                  {showChapterSkeleton ? (
                    <div className="mt-4" role="status" aria-busy="true" aria-live="polite" data-testid="chapter-skeleton">
                      <p className="mb-2 text-body-sm text-muted-foreground">{t("chapterList.loading")}</p>
                      <div className="overflow-hidden rounded-lg border">
                        <div className="sticky top-0 border-b bg-card px-4 py-2 text-body-sm font-semibold text-muted-foreground">
                          <div className="grid grid-cols-3 gap-2">
                            <span>✓</span>
                            <span>#</span>
                            <span>{t("chapterList.title")}</span>
                          </div>
                        </div>
                        <div className="divide-y">
                          {[0, 1, 2, 3, 4, 5].map((i) => (
                            <div key={i} className="grid grid-cols-3 gap-2 px-4 py-3">
                              <div className="h-4 animate-pulse rounded bg-muted" />
                              <div className="h-4 animate-pulse rounded bg-muted" />
                              <div className="h-4 animate-pulse rounded bg-muted" />
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {/* error empty state */}
                  {showChapterError ? (
                    <div className="mt-4 space-y-3">
                      <div
                        role="alert"
                        aria-live="assertive"
                        className="rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive"
                      >
                        {t(chapterError === "VALUE_ERROR" ? "chapterList.errorValue" : "chapterList.errorList", { defaultValue: t("toast.searchFailed") })}:{" "}
                        {chapterError}
                      </div>
                      <div className="rounded-lg border border-dashed bg-card p-6 text-center">
                        <p className="text-body font-semibold">{t("chapterList.empty")}</p>
                        <button
                          ref={retryRef}
                          type="button"
                          onClick={() => {
                            const url = selectedUrl;
                            if (typeof window === "undefined") return;
                            if (retryTimeoutRef.current) window.clearTimeout(retryTimeoutRef.current);
                            setSelectedUrl(null);
                            retryTimeoutRef.current = window.setTimeout(() => setSelectedUrl(url), 0);
                          }}
                          className="mt-3 rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {t("chapterList.retry")}
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {/* actual list */}
                  {showChapterList ? (
                    <div className="mt-4">
                      <ChapterList
                        chapters={chapterList}
                        selected={selected}
                        from={from}
                        to={to}
                        anchor={anchor}
                        busy={fetching || audioBuilding}
                        onSelectedChange={setSelected}
                        onRangeChange={handleRangeChange}
                        onAnchorChange={setAnchor}
                        onStartFetch={handleStartFetchRange}
                        onPreview={handlePreview}
                        hideRangeBar={true}
                      />
                    </div>
                  ) : null}

                  {/* empty list but no error — still show Brak listy if needed */}
                  {showChapterEmpty ? (
                    <div className="mt-4 rounded-lg border border-dashed bg-card p-6 text-center" role="status" aria-live="polite">
                      <p className="text-body font-semibold">{t("chapterList.empty")}</p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

         {previewChapter ? (
           <Preview
             open={previewIdx != null}
             onClose={() => setPreviewIdx(null)}
             chapterUrl={previewChapter.url}
             chapterTitle={previewChapter.title}
             chapterIndex={previewChapter.index}
           />
         ) : null}
      </div>
    </div>
  );
}
