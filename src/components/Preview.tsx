import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { previewChapter, getSelectors, saveSelectors, clearSelectors, isPreviewResult } from "@/lib/sidecar";

type PreviewProps = {
  open: boolean;
  onClose: () => void;
  chapterUrl: string;
  chapterTitle: string;
  chapterIndex: number;
};

export default function Preview({ open, onClose, chapterUrl, chapterTitle, chapterIndex }: PreviewProps): JSX.Element | null {
  const [tab, setTab] = useState<"original" | "cleaned">("cleaned");
  const [start, setStart] = useState<string>("div#chapter-content");
  const [end, setEnd] = useState<string>("");
  const [defaultStart, setDefaultStart] = useState<string>("div#chapter-content");
  const [defaultEnd, setDefaultEnd] = useState<string>("");
  const [originalHtml, setOriginalHtml] = useState<string>("");
  const [originalText, setOriginalText] = useState<string>("");
  const [cleanedHtml, setCleanedHtml] = useState<string>("");
  const [cleanedText, setCleanedText] = useState<string>("");
  const [filteredText, setFilteredText] = useState<string>("");
  const [filteredHtml, setFilteredHtml] = useState<string>("");
  const [removedCount, setRemovedCount] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);
  const startInputRef = useRef<HTMLInputElement>(null);
  const endInputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // load default selectors on open
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getSelectors({ url: chapterUrl })
      .then((res) => {
        if (cancelled) return;
        if (res.result && typeof res.result === "object") {
          const r = res.result as Record<string, unknown>;
          const s = r.start as string | null;
          const e = r.end as string | null;
          const ds = (r.defaultStart as string) ?? "div#chapter-content";
          const de = (r.defaultEnd as string | null) ?? "";
          if (s !== null && s !== undefined) setStart(s);
          else setStart(ds);
          if (e !== null && e !== undefined) setEnd(e);
          else setEnd(de);
          setDefaultStart(ds);
          setDefaultEnd(de);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open, chapterUrl]);

  // focus trap + Esc + focus start input
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const timer = window.setTimeout(() => startInputRef.current?.focus(), 0);
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [open, onClose]);

  // live re-parse debounce 300ms via previewChapter — stale guard + filter chip
  useEffect(() => {
    if (!open) return;
    if (abortRef.current) abortRef.current.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;
    const seq = ++seqRef.current;
    const t = window.setTimeout(() => {
      previewChapter({ url: chapterUrl, start: start || null, end: end || null }, { signal: ctl.signal })
        .then((res) => {
          if (ctl.signal.aborted) return;
          if (seq !== seqRef.current) return;
          if (res.error) {
            const code = res.error.code;
            if (code === "VALUE_ERROR" && res.error.message.includes("invalid selector")) {
              setError(res.error.message);
              // keep previous cleaned
              return;
            }
            if (code === "VALUE_ERROR" && res.error.message.includes("invalid regex")) {
              setError(res.error.message);
              return;
            }
            setError(res.error.message);
            return;
          }
          if (isPreviewResult(res)) {
            const r = res.result as {
              originalHtml: string;
              originalText: string;
              html: string;
              text: string;
              filteredHtml?: string;
              filteredText?: string;
              removedCount?: number;
              start: string | null;
              end: string | null;
            };
            setOriginalHtml(r.originalHtml);
            setOriginalText(r.originalText);
            setCleanedHtml(r.html);
            setCleanedText(r.text);
            setFilteredHtml(r.filteredHtml ?? r.html);
            setFilteredText(r.filteredText ?? r.text);
            setRemovedCount(typeof r.removedCount === "number" ? r.removedCount : 0);
            setError(null);
          }
        })
        .catch((e: unknown) => {
          if (ctl.signal.aborted) return;
          const msg = e instanceof Error ? e.message : String(e);
          if (msg.includes("aborted")) return;
          setError(msg);
        });
    }, 300);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [open, chapterUrl, start, end]);

  // reload on filters-updated event (dispatched by Filters.tsx after add/delete)
  useEffect(() => {
    if (!open) return;
    const handler = (): void => {
      // trigger re-fetch by bumping seq and calling preview again without waiting debounce
      if (abortRef.current) abortRef.current.abort();
      const ctl = new AbortController();
      abortRef.current = ctl;
      const seq = ++seqRef.current;
      previewChapter({ url: chapterUrl, start: start || null, end: end || null }, { signal: ctl.signal })
        .then((res) => {
          if (ctl.signal.aborted) return;
          if (seq !== seqRef.current) return;
          if (res.error) {
            if (res.error.code === "VALUE_ERROR" && res.error.message.includes("invalid regex")) {
              setError(res.error.message);
              return;
            }
            return;
          }
          if (isPreviewResult(res)) {
            const r = res.result as { html: string; text: string; filteredHtml?: string; filteredText?: string; removedCount?: number; originalHtml: string; originalText: string };
            setCleanedHtml(r.html);
            setCleanedText(r.text);
            setFilteredHtml(r.filteredHtml ?? r.html);
            setFilteredText(r.filteredText ?? r.text);
            setRemovedCount(typeof r.removedCount === "number" ? r.removedCount : 0);
          }
        })
        .catch(() => {});
    };
    window.addEventListener("filters-updated", handler as EventListener);
    return () => window.removeEventListener("filters-updated", handler as EventListener);
  }, [open, chapterUrl, start, end]);

  // initial fetch on open without debounce? the effect above already handles, but ensure immediate on open
  useEffect(() => {
    if (!open) return;
    // reset texts on chapter change
    setError(null);
    setOriginalHtml("");
    setOriginalText("");
    setCleanedHtml("");
    setCleanedText("");
    setFilteredHtml("");
    setFilteredText("");
    setRemovedCount(0);
  }, [open, chapterUrl]);

  if (!open) return null;

  const hasContent = cleanedText.trim().length > 0;
  const diffCount = originalText.length - cleanedText.length;

  const handleReset = (): void => {
    setError(null);
    setStart(defaultStart);
    setEnd(defaultEnd);
    // also clear override on backend
    clearSelectors({ url: chapterUrl }).catch(() => {});
  };

  const handleSave = async (): Promise<void> => {
    setSaving(true);
    setError(null);
    try {
      const res = await saveSelectors({ url: chapterUrl, start: start || null, end: end || null });
      if (res.error) {
        setError(res.error.message);
        return;
      }
      // success — keep current selectors as override
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" aria-hidden={false}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} data-testid="preview-overlay" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Podgląd rozdziału ${chapterIndex}: ${chapterTitle}`}
        className="relative z-10 flex max-h-[90vh] w-[1120px] max-w-[95vw] flex-col rounded-xl border bg-card shadow-lg"
        data-testid="preview-dialog"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-heading font-semibold">
              Podgląd {chapterIndex}: {chapterTitle}
            </h2>
            <p className="mono mt-1 truncate text-mono text-body-sm text-muted-foreground" title={chapterUrl}>
              {chapterUrl}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Zamknij podgląd"
            className="rounded-md p-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="preview-close"
          >
            ✕
          </button>
        </div>

        {/* Controls */}
        <div className="grid grid-cols-1 gap-3 border-b bg-muted/30 px-6 py-3 md:grid-cols-[1fr_1fr_auto]">
          <label className="flex flex-col gap-1">
            <span className="text-body-sm font-medium">start selector</span>
            <input
              ref={startInputRef}
              value={start}
              onChange={(e) => setStart(e.target.value)}
              placeholder='div#chapter-content'
              className="mono h-9 rounded-md border border-input bg-card px-3 text-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="preview-start-input"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-body-sm font-medium">end selector</span>
            <input
              ref={endInputRef}
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              placeholder="(opcjonalnie) #end"
              className="mono h-9 rounded-md border border-input bg-card px-3 text-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="preview-end-input"
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={handleReset}
              className="h-9 rounded-md border bg-card px-4 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="preview-reset"
            >
              Reset do adaptera
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="h-9 rounded-md bg-accent px-4 text-body font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="preview-save"
            >
              {saving ? "Zapisywanie…" : "Zastosuj"}
            </button>
          </div>
        </div>
        {error ? (
          <div
            role="alert"
            aria-live="polite"
            className="mx-6 mt-3 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive"
            data-testid="preview-error"
          >
            {error.includes("invalid selector") ? `invalid selector — ${error}` : error}
          </div>
        ) : null}
        {!hasContent && !error && cleanedHtml === "" && originalHtml === "" ? (
          <div className="px-6 py-2 text-body-sm text-muted-foreground">Ładowanie…</div>
        ) : null}
        {!hasContent && !error && cleanedText === "" && cleanedHtml !== "" ? (
          <div
            className="mx-6 mt-3 rounded-md border border-warning/20 bg-warning/10 px-3 py-2 text-body-sm text-warning-foreground"
            data-testid="preview-empty"
          >
            Nie wyizolowano — spróbuj poprawić selektor
          </div>
        ) : null}
        {hasContent ? (
          <div className="mx-6 mt-2 flex flex-wrap items-center gap-2 text-body-sm text-muted-foreground" data-testid="preview-diff">
            <span className="rounded-full bg-accent/10 px-2 py-0.5 text-accent">oczyszczone</span>
            <span>{cleanedText.length} znaków • usunięto ~{diffCount > 0 ? diffCount : 0} znaków nav</span>
            {removedCount > 0 ? (
              <span className="rounded-full bg-warning/10 px-2 py-0.5 text-warning border border-warning/20" data-testid="filter-chip">
                Usunięto {removedCount} {removedCount === 1 ? "linia" : removedCount < 5 ? "linie" : "linii"} przez filtry
              </span>
            ) : (
              <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground" data-testid="filter-chip">
                Usunięto 0 linii
              </span>
            )}
          </div>
        ) : null}

        {/* Content 40/60 split — single-col <1024 per responsive spec */}
        <div className="flex flex-col gap-0 overflow-hidden lg:flex-row" style={{ minHeight: 0 }}>
          {/* Tabs header */}
          <div className="flex w-full flex-col border-t lg:w-[40%] lg:border-r lg:border-t-0">
            <div className="flex gap-1 border-b bg-muted/20 p-1" role="tablist" aria-label="Podgląd tabs">
              <button
                role="tab"
                aria-selected={tab === "original"}
                data-testid="preview-tab-original"
                onClick={() => setTab("original")}
                className={
                  "flex-1 rounded-md px-3 py-2 text-body-sm font-medium " +
                  (tab === "original"
                    ? "bg-card shadow-sm border text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
              >
                Oryginał
              </button>
              <button
                role="tab"
                aria-selected={tab === "cleaned"}
                data-testid="preview-tab-cleaned"
                onClick={() => setTab("cleaned")}
                className={
                  "flex-1 rounded-md px-3 py-2 text-body-sm font-medium " +
                  (tab === "cleaned"
                    ? "bg-accent text-accent-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
              >
                Oczyszczone
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4" style={{ maxHeight: "50vh" }} aria-live="polite">
              {tab === "original" ? (
                <div data-testid="preview-original">
                  {originalText ? (
                    <p className="whitespace-pre-wrap text-body leading-relaxed">{originalText.slice(0, 8000)}</p>
                  ) : (
                    <p className="text-body-sm text-muted-foreground">— brak treści oryginału —</p>
                  )}
                  <details className="mt-4">
                    <summary className="cursor-pointer text-body-sm text-muted-foreground">Pokaż HTML</summary>
                    <pre className="mono mt-2 max-h-40 overflow-auto rounded border bg-muted p-2 text-mono">{originalHtml.slice(0, 8000)}</pre>
                  </details>
                </div>
              ) : (
                <div data-testid="preview-cleaned">
                  {(removedCount > 0 ? filteredText : cleanedText) ? (
                    <p className="whitespace-pre-wrap text-body leading-relaxed">
                      {(removedCount > 0 ? filteredText : cleanedText).slice(0, 8000)}
                    </p>
                  ) : (
                    <p className="text-body-sm text-muted-foreground">— brak wyizolowanej treści —</p>
                  )}
                  {removedCount > 0 ? (
                    <p className="mt-2 text-body-sm text-muted-foreground">Wyświetlono po filtrach — usunięto {removedCount} linii</p>
                  ) : null}
                  <details className="mt-4">
                    <summary className="cursor-pointer text-body-sm text-muted-foreground">Pokaż HTML</summary>
                    <pre className="mono mt-2 max-h-40 overflow-auto rounded border bg-muted p-2 text-mono">
                      {(removedCount > 0 ? filteredHtml : cleanedHtml).slice(0, 8000)}
                    </pre>
                  </details>
                </div>
              )}
            </div>
          </div>
          <div className="hidden w-[60%] flex-col overflow-auto border-l lg:flex" style={{ maxHeight: "50vh" }}>
            <div className="border-b bg-muted/20 px-4 py-2 text-body-sm font-medium text-muted-foreground">Podgląd renderowany</div>
            <div className="prose prose-sm max-w-none p-4 text-body" data-testid="preview-rendered">
              {tab === "original" ? (
                <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(originalHtml.slice(0, 20000)) }} />
              ) : (
                <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize((removedCount > 0 ? filteredHtml : cleanedHtml).slice(0, 20000)) }} />
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t px-6 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Zamknij
          </button>
        </div>
      </div>
    </div>
  );
}
