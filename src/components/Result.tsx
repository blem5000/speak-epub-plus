import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { t } from "@/i18n";
import type { EpubResult } from "@/lib/sidecar";
import { revealPath } from "@/lib/sidecar";

type ResultProps = {
  result: EpubResult | null;
  building: boolean;
  error: string | null;
  missing?: string[] | null;
  canBuild: boolean;
  onBuild: () => void;
  from?: number;
  to?: number;
};

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Result({
  result,
  building,
  error,
  missing,
  canBuild,
  onBuild,
  from,
  to,
}: ResultProps): JSX.Element {
  const [keepEpub, setKeepEpub] = useState<boolean>(true);
  const [keepLoading, setKeepLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const [showMessages, setShowMessages] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const mod = await import("@/lib/sidecar");
        const fn = (mod as unknown as { getStore?: () => Promise<import("@/lib/sidecar").RpcResponse> }).getStore;
        if (typeof fn !== "function") {
          if (alive) setKeepLoading(false);
          return;
        }
        const res = await fn();
        if (!alive) return;
        const data = res.result as Record<string, unknown> | undefined;
        if (data && typeof data.keepEPUB === "boolean") {
          setKeepEpub(data.keepEPUB as boolean);
        }
        setKeepLoading(false);
      } catch {
        if (alive) setKeepLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const handleKeepToggle = async (checked: boolean): Promise<void> => {
    setKeepEpub(checked);
    try {
      const mod = await import("@/lib/sidecar");
      const fn = (mod as unknown as { setStore?: (p: Record<string, unknown>) => Promise<import("@/lib/sidecar").RpcResponse> }).setStore;
      if (typeof fn !== "function") {
        setToast(t("result.keepEpubSaved") ?? "Zapisano");
        window.setTimeout(() => setToast(null), 1500);
        return;
      }
      const res = await fn({ keepEPUB: checked });
      if (res.error) {
        setToast(res.error.message);
      } else {
        setToast(t("result.keepEpubSaved") ?? "Zapisano");
        window.setTimeout(() => setToast(null), 1500);
      }
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
    }
  };

  const handleOpen = async (target: string | undefined): Promise<void> => {
    if (!target) return;
    const path = target;
    // Try Tauri opener plugin
    try {
      await invoke("plugin:opener|open_path", { path });
      return;
    } catch {
      // fallback to shell open via plugin:shell?
      try {
        await invoke("plugin:shell|open", { path });
        return;
      } catch {
        // fallback window.open for file
        try {
          window.open(`file://${path}`, "_blank");
        } catch {}
      }
    }
  };

  const handleOpenFile = (): void => {
    void handleOpen(result?.path);
  };

  const handleOpenFolder = (): void => {
    // Reveal the file in its folder (Explorer opens with the file selected).
    if (!result?.path) return;
    revealPath(result.path).catch((e: unknown) => {
      setToast(e instanceof Error ? e.message : String(e));
      window.setTimeout(() => setToast(null), 4000);
    });
  };

  const isProxy =
    (result as unknown as Record<string, unknown>)?.epubcheck_proxy === true ||
    (result as unknown as Record<string, unknown>)?.is_proxy === true ||
    (Array.isArray(result?.messages) && result.messages.some((m) => /proxy/i.test(m)));

  const badgeText = building
    ? t("result.building")
    : !result
      ? t("result.notBuilt")
      : result.epubcheck_ok
        ? isProxy
          ? t("result.epubcheckProxy")
          : t("result.epubcheckOk")
        : t("result.epubcheckFail");

  const badgeColor = !result
    ? "bg-muted text-muted-foreground"
    : result.epubcheck_ok
      ? isProxy
        ? "bg-warning/10 text-warning border-warning/20 border"
        : "bg-success/10 text-success border-success/20 border"
      : "bg-destructive/10 text-destructive border-destructive/20 border";

  const badgeIcon = !result ? "" : result.epubcheck_ok ? (isProxy ? "~ " : "✓ ") : "✗ ";

  return (
    <section
      className="rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("result.title")}
      data-testid="result-section"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-heading font-semibold">{t("result.title")}</h2>
        <span
          data-testid="epubcheck-badge"
          className={`rounded-full px-3 py-1 text-body-sm font-medium ${badgeColor}`}
        >
          {badgeIcon}
          {badgeText}
        </span>
      </div>

      {building ? (
        <div
          className="mt-4 flex items-center gap-2 text-body-sm text-muted-foreground"
          data-testid="result-building"
          role="status"
          aria-live="polite"
        >
          <span
            aria-hidden="true"
            className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
          />
          {t("result.building")}…
        </div>
      ) : null}

      {!building && !result ? (
        <div className="mt-4 rounded-md border border-dashed bg-muted/30 p-4 text-center" data-testid="result-empty">
          <p className="text-body-sm text-muted-foreground">{t("result.notBuilt")}</p>
          <button
            type="button"
            onClick={onBuild}
            disabled={!canBuild}
            data-testid="result-build"
            className="mt-3 rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("result.buildEpub") ?? "Build EPUB"}
          </button>
          {error ? (
            <div role="alert" className="mt-2 text-body-sm text-destructive" data-testid="result-error">
              {error} {missing && missing.length > 0 ? `— ${missing.slice(0, 3).join(", ")}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}

      {!building && result ? (
        <div className="mt-4 space-y-3">
          <div className="space-y-1">
            <div className="text-body-sm font-medium text-muted-foreground">{t("result.path")}</div>
            <div
              data-testid="result-path"
              className="mono break-all rounded-md border bg-muted p-2 text-mono text-xs"
              style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "12px" }}
            >
              {result.path}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-body-sm">
            <span data-testid="result-size" className="rounded-full bg-muted px-3 py-1">
              {t("result.size")}: {humanSize(result.size)}
            </span>
            <span data-testid="result-chapters" className="rounded-full bg-muted px-3 py-1">
              {t("result.chaptersCount", { count: String(result.chapter_count) })}
            </span>
            {from !== undefined && to !== undefined ? (
              <span className="text-muted-foreground">
                {from}–{to}
              </span>
            ) : null}
          </div>

          {Array.isArray(result.messages) && result.messages.length > 0 ? (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setShowMessages((s) => !s)}
                className="text-body-sm text-accent underline"
                data-testid="epubcheck-toggle"
              >
                {showMessages ? "Ukryj" : "Pokaż"} epubcheck
              </button>
              {showMessages ? (
                <pre
                  className="mono mt-2 max-h-32 overflow-auto rounded-md border bg-muted p-2 text-mono text-xs"
                  data-testid="epubcheck-messages"
                >
                  {result.messages.join("\n")}
                </pre>
              ) : null}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleOpenFile}
              data-testid="open-file"
              className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("result.openFile")}
            </button>
            <button
              type="button"
              onClick={handleOpenFolder}
              data-testid="open-folder"
              className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("result.openFolder")}
            </button>
            <button
              type="button"
              onClick={onBuild}
              disabled={!canBuild || building}
              data-testid="result-rebuild"
              className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("result.buildEpub") ?? "Build EPUB"}
            </button>
          </div>

          {error ? (
            <div role="alert" className="text-body-sm text-destructive" data-testid="result-error">
              {error} {missing && missing.length > 0 ? `— ${missing.slice(0, 2).join(", ")}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* keepEPUB switch */}
      <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4">
        <label className="flex items-center gap-2 text-body-sm">
          <input
            type="checkbox"
            checked={keepEpub}
            onChange={(e) => void handleKeepToggle(e.target.checked)}
            disabled={keepLoading}
            data-testid="keep-epub"
            className="h-4 w-4 rounded border-input"
          />
          <span>{t("result.keepEpub")}</span>
        </label>
        {toast ? (
          <span className="text-body-sm text-muted-foreground" role="status" aria-live="polite">
            {toast}
          </span>
        ) : null}
      </div>

      {error && error.includes("CACHE_MISS") ? (
        <div className="mt-2 rounded-md border border-destructive/20 bg-destructive/10 px-3 py-2 text-body-sm text-destructive" data-testid="cache-miss">
          {t("result.cacheMiss")}: {missing?.slice(0, 3).join(", ") ?? error}
        </div>
      ) : null}
    </section>
  );
}
