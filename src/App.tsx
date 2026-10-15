import { useEffect, useRef, useState, useCallback } from "react";
import { t, getLocale, setLocale } from "./i18n";
import { buildEpub, callSidecar, getStore, isEpubResult, setStore, type EpubResult } from "./lib/sidecar";
import FindInput from "./components/FindInput";
import ResultsTable from "./components/ResultsTable";
import ChapterList from "./components/ChapterList";
import Preview from "./components/Preview";
import Filters from "./components/Filters";
import FiltersWindow from "./components/FiltersWindow";
import Result from "./components/Result";
import Audiobook from "./components/Audiobook";
import UpdaterBanner from "./components/UpdaterBanner";
import Queue from "./components/Queue";
import ThrottleBadge from "./components/ThrottleBadge";
import ProgressTrack from "./components/ProgressTrack";
import Settings from "./components/Settings";
import { useChapterList } from "./hooks/useChapterList";
import { useDebouncedSearch } from "./hooks/useDebouncedSearch";
import { useFetcher } from "./hooks/useFetcher";
import { useGlobalKeys } from "./hooks/useGlobalKeys";
import { selectedUrlsForFetch as urlsForFetch } from "./lib/selection";

export default function App(): JSX.Element {
  const [locale, setLocaleState] = useState(getLocale());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [filtersWindowOpen, setFiltersWindowOpen] = useState(false);
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

  // Restore persisted UI locale from Core on mount ("" = auto-detect from system)
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await getStore();
        if (!alive) return;
        const saved = (res?.result as Record<string, unknown> | undefined)?.locale;
        if (saved === "en" || saved === "pl") {
          setLocale(saved);
          setLocaleState(saved);
        }
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
    if (filtersWindowOpen) {
      setFiltersWindowOpen(false);
      return true;
    }
    if (settingsOpen) {
      setSettingsOpen(false);
      return true;
    }
    return false;
  }, [previewIdx, filtersWindowOpen, settingsOpen]);
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
  const logPaneRef = useRef<HTMLDivElement>(null);

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

  // EPUB build — Story 2.4
  const selectedResult = results.find((r) => r.url === selectedUrl) ?? null;
  const buildTitle = selectedResult?.title ?? chapterList[0]?.title ?? "book";
  const buildAuthor = (selectedResult as unknown as { author?: string })?.author ?? null;
  const canBuild = !!(hasSelectedUrl && !chapterLoading && N > 0 && !fetching && !epubBuilding);

  const handleBuildEpub = useCallback(async (): Promise<void> => {
    if (!canBuild) return;
    const urls = selectedUrlsForFetch;
    if (urls.length === 0) return;
    setEpubBuilding(true);
    setEpubError(null);
    setEpubMissing(null);
    // mark cleaning for each chapter in range
    const fromC = Math.max(1, Math.min(from, N));
    const toC = Math.max(1, Math.min(to, N));
    const lo = Math.min(fromC, toC);
    const hi = Math.max(fromC, toC);
    // set all in range to cleaning — only existing indices
    setStatuses((prev) => {
      const next = { ...prev };
      const existing = new Set(chapterList.map((c) => c.index));
      for (let i = lo; i <= hi; i++) {
        if (!existing.has(i)) continue;
        if (selectedUrlsForFetch.some((u) => chapterList.find((c) => c.url === u && c.index === i))) {
          next[i] = "cleaning";
        } else if (selected.size === 0) {
          next[i] = "cleaning";
        }
      }
      return next;
    });
    appendLogs([`building epub ${lo}->${hi}`, `cleaning chapter ${lo}`]);
    try {
      const res = await buildEpub({
        novelUrl: selectedUrl ?? "",
        from: lo,
        to: hi,
        title: buildTitle,
        author: buildAuthor ?? undefined,
        coverUrl: chapterCover ?? undefined,
        urls,
      });
      if (res.error) {
        const code = res.error.code;
        const msg = res.error.message;
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
        } else if (code === "VALUE_ERROR") {
          setEpubError(`VALUE_ERROR: ${msg}`);
          appendLogs([`VALUE_ERROR ${msg}`]);
        } else {
          setEpubError(`${code}: ${msg}`);
          appendLogs([`error ${code}: ${msg}`]);
        }
        return;
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
      } else {
        setEpubError("unknown epub result");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setEpubError(msg);
      appendLogs([`epub error ${msg}`]);
    } finally {
      setEpubBuilding(false);
    }
  }, [canBuild, selectedUrl, from, to, buildTitle, buildAuthor, chapterCover, selectedUrlsForFetch, N, chapterList, selected.size, appendLogs, setStatuses]);

  return (
    <div className="min-h-screen bg-background text-foreground">
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
              data-testid="filters-window-button"
              aria-label={(t("filters.title") as string) || "Filters"}
              title={(t("filters.title") as string) || "Filters"}
              onClick={() => setFiltersWindowOpen(true)}
              className="rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              ♢
            </button>
            <button
              type="button"
              data-testid="settings-gear"
              aria-label={(t("settings.gear") as string) || "Settings"}
              title={(t("settings.gear") as string) || "Settings"}
              onClick={() => setSettingsOpen(true)}
              className="rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              ⚙
            </button>
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
        <Settings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
        <FiltersWindow open={filtersWindowOpen} onClose={() => setFiltersWindowOpen(false)} />
        <UpdaterBanner />

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
              <ResultsTable results={results} selectedUrl={selectedUrl} onSelect={setSelectedUrl} />
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
        </section>

        {/* Chapter List surface — spec 1.4 */}
        {hasSelectedUrl ? (
          <section className="mt-6 rounded-lg border bg-card p-6 shadow-sm" aria-label={t("chapterList.title")}>
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-heading font-semibold">{t("chapterList.title")}</h2>
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
                />
              </div>
            ) : null}

            {/* empty list but no error — still show Brak listy if needed */}
            {showChapterEmpty ? (
              <div className="mt-4 rounded-lg border border-dashed bg-card p-6 text-center" role="status" aria-live="polite">
                <p className="text-body font-semibold">{t("chapterList.empty")}</p>
              </div>
            ) : null}
          </section>
        ) : null}

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

        {/* Result — Story 2.4 EPUB assembly + epubcheck */}
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

        {/* Audiobook — Step 7: MP3/M4B/M4A from the same fetched cache */}
        <div className="mt-6">
          <Audiobook
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
          />
        </div>

        {/* Filters — Story 2.3 plain+regex gate */}
        <div className="mt-6">
          <Filters />
        </div>
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
