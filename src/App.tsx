import { useEffect, useState } from "react";
import { t, getLocale, setLocale } from "./i18n";
import { callSidecar } from "./lib/sidecar";

export default function App(): JSX.Element {
  const [locale, setLocaleState] = useState(getLocale());
  const [rpcStatus, setRpcStatus] = useState<string>("idle");
  const [storePreview, setStorePreview] = useState<string>("");

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

  const toggleLocale = (): void => {
    const next = locale === "en" ? "pl" : "en";
    setLocale(next);
    setLocaleState(next);
  };

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

        {/* Token demo card */}
        <section className="rounded-lg border bg-card p-6 shadow-sm">
          <h2 className="text-heading font-semibold">{t("tokens.title")}</h2>
          <p className="text-body-sm text-muted-foreground">{t("tokens.hint")}</p>

          <div className="mt-4 grid gap-4">
            {/* Input demo */}
            <input
              placeholder={t("find.placeholder")}
              className="h-11 rounded-md border border-input bg-card px-4 text-body placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
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
              <div
                className="h-full rounded-full bg-accent"
                style={{ width: "42%" }}
              />
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

        {/* Placeholder for EPIC 1.3/1.4 — mocks only */}
        <section className="mt-6 rounded-lg border border-dashed bg-card p-6">
          <p className="text-body-sm text-muted-foreground">{t("placeholder.discovery")}</p>
        </section>
      </div>
    </div>
  );
}
