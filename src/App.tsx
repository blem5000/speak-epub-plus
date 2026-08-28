import { useEffect, useRef, useState } from "react";
import { t, getLocale, setLocale } from "./i18n";
import { callSidecar } from "./lib/sidecar";
import FindInput from "./components/FindInput";
import ResultsTable from "./components/ResultsTable";
import ChapterList from "./components/ChapterList";
import { useChapterList } from "./hooks/useChapterList";
import { useDebouncedSearch } from "./hooks/useDebouncedSearch";

export default function App(): JSX.Element {
  const [locale, setLocaleState] = useState(getLocale());
  const [rpcStatus, setRpcStatus] = useState<string>("idle");
  const [storePreview, setStorePreview] = useState<string>("");
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

  useEffect(() => {
    // Demo sidecar round-trip on mount (AD-4 spike)
    callSidecar("hello", { from: "gui" })
      .then((res) => {
        setRpcStatus(JSON.stringify(res));
      })
      .catch((e) => setRpcStatus(`sidecar failed: ${(e as Error).message}`));

    // Load store.json preview via tauri-plugin-store (mirrors CLI flags)
    // Keep placeholder; actual store handled in Rust + core/config.py
    setStorePreview('{"voice":"pl-PL-ZofiaNeural","parallel":3}');
  }, []);

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

  // P7: swap from/to if inverted after clamp (a>b) — separate tick to read updated values
  useEffect(() => {
    const N = chapterList.length;
    if (N > 0 && from > to) {
      setFrom(to);
      setTo(from);
    }
  }, [from, to, chapterList.length]);

  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current && typeof window !== "undefined") window.clearTimeout(retryTimeoutRef.current);
    };
  }, []);

  const toggleLocale = (): void => {
    const next = locale === "en" ? "pl" : "en";
    setLocale(next);
    setLocaleState(next);
  };

  const trimmedQuery = query.trim();
  const showNoResults = !searching && trimmedQuery.length > 0 && results.length === 0;

  const handleRangeChange = (nextFrom: number, nextTo: number): void => {
    setFrom(nextFrom);
    setTo(nextTo);
  };

  const handlePreview = (idx: number): void => {
    // Preview placeholder for Epic 2 — log only in dev
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.debug(`Preview placeholder for chapter ${idx}`);
    }
  };

  const hasSelectedUrl = !!(selectedUrl && selectedUrl.trim());
  const showChapterSkeleton = hasSelectedUrl && chapterLoading;
  const showChapterList = hasSelectedUrl && !chapterLoading && chapterList.length > 0 && !chapterError;
  const showChapterError = hasSelectedUrl && !chapterLoading && !!chapterError;
  const showChapterEmpty = hasSelectedUrl && !chapterLoading && !chapterError && chapterList.length === 0;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* Header */}
        <header className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-display font-semibold tracking-tight">
              {t("app.title")}
            </h1>
            <p className="text-body-sm text-muted-foreground">
              {t("app.subtitle")} — {t("find.hint")}
            </p>
          </div>
          <button
            type="button"
            onClick={toggleLocale}
            className="rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted"
            aria-label="Toggle locale"
          >
            {locale.toUpperCase()}
          </button>
        </header>

        {/* Token demo card — keep per spec */}
        <section className="rounded-lg border bg-card p-6 shadow-sm">
          <h2 className="text-heading font-semibold">{t("tokens.title")}</h2>
          <p className="text-body-sm text-muted-foreground">{t("tokens.hint")}</p>

          <div className="mt-4 grid gap-4">
            {/* Input demo — keep token demo */}
            <input
              placeholder={t("find.placeholder")}
              className="h-11 rounded-md border border-input bg-card px-4 text-body placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              readOnly
              aria-hidden="true"
              tabIndex={-1}
            />

            {/* Button accent demo */}
            <div className="flex gap-2">
              <button className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring">
                {t("find.cta")}
              </button>
              <button className="rounded-md bg-primary px-4 py-2 text-body font-medium text-primary-foreground">
                {t("tokens.buildEpub")}
              </button>
            </div>

            {/* Pill / progress demo */}
            <div className="rounded-full bg-muted px-3 py-1 text-body-sm w-fit">
              {t("chapterList.selected", { count: 6, total: 142 })}
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted">
              <div className="h-full rounded-full bg-accent" style={{ width: "42%" }} />
            </div>

            {/* Mono sample */}
            <pre className="mono rounded-md border bg-muted p-3 text-mono">
              {t("tokens.monoSample")}
              {"\n"}
              {t("tokens.monoSample2")}
            </pre>

            {/* RPC / store preview */}
            <div className="rounded-md border bg-muted p-3 text-body-sm">
              <div>
                <span className="font-semibold">{t("tokens.rpcLabel")}</span> {rpcStatus}
              </div>
              <div className="mono mt-1 text-mono">
                {t("tokens.storePreview")} {storePreview}
              </div>
            </div>

            <p className="text-body-sm text-muted-foreground">{t("tokens.windowNote")}</p>
          </div>
        </section>

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
                  onSelectedChange={setSelected}
                  onRangeChange={handleRangeChange}
                  onAnchorChange={setAnchor}
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
      </div>
    </div>
  );
}
