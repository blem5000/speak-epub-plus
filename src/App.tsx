import { useEffect, useRef, useState } from "react";
import { t, getLocale, setLocale } from "./i18n";
import { callSidecar } from "./lib/sidecar";
import FindInput from "./components/FindInput";
import ResultsTable from "./components/ResultsTable";
import { useDebouncedSearch } from "./hooks/useDebouncedSearch";

export default function App(): JSX.Element {
  const [locale, setLocaleState] = useState(getLocale());
  const [rpcStatus, setRpcStatus] = useState<string>("idle");
  const [storePreview, setStorePreview] = useState<string>("");
  const [query, setQuery] = useState("");
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const ctaRef = useRef<HTMLButtonElement>(null);
  const { searching, results, error } = useDebouncedSearch(query, 400);

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

  const toggleLocale = (): void => {
    const next = locale === "en" ? "pl" : "en";
    setLocale(next);
    setLocaleState(next);
  };

  const trimmedQuery = query.trim();
  const showNoResults = !searching && trimmedQuery.length > 0 && results.length === 0;

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
      </div>
    </div>
  );
}
