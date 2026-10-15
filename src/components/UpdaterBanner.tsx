import { useEffect, useRef, useState } from "react";
import { t } from "@/i18n";
import {
  applyUpdate,
  canInstallUpdates,
  checkForUpdates,
  compareVersions,
  discardUpdate,
  downloadUpdate,
  getCurrentVersion,
  getUpdatePrefs,
  onUpdateFound,
  openReleaseUrl,
  skipVersion,
  type DownloadProgress,
  type UpdateInfo,
} from "@/lib/updater";

type Phase = "idle" | "downloading" | "applying" | "error";

/**
 * Startup update check — silent unless a newer GitHub Release exists.
 * Install downloads the portable ZIP with progress, then hands off to Rust
 * (hidden .bat waits for our PID, extracts, robocopies, restarts).
 * Skip persists for that version (`updateSkipped`); Later hides for the session.
 */
export default function UpdaterBanner(): JSX.Element | null {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<DownloadProgress>({ received: 0, total: 0 });
  const [error, setError] = useState("");
  const aliveRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    const unsub = onUpdateFound((found) => {
      if (!aliveRef.current) return;
      setInfo(found);
      setPhase("idle");
      setError("");
    });
    void (async () => {
      try {
        const prefs = await getUpdatePrefs();
        if (!aliveRef.current || !prefs.auto) return;
        const current = await getCurrentVersion();
        if (!aliveRef.current || !current) return;
        const found = await checkForUpdates(current);
        if (!aliveRef.current || !found) return;
        if (prefs.skipped && compareVersions(prefs.skipped, found.latest) === 0) return;
        setInfo(found);
      } catch {
        // silent — update check never blocks startup
      }
    })();
    return () => {
      aliveRef.current = false;
      unsub();
      abortRef.current?.abort();
    };
  }, []);

  if (!info) return null;

  const handleInstall = (): void => {
    if (!info.zipUrl) {
      void openReleaseUrl(info.url);
      return;
    }
    if (!canInstallUpdates()) {
      setPhase("error");
      setError(t("updater.devBlocked"));
      return;
    }
    const ac = new AbortController();
    abortRef.current = ac;
    setPhase("downloading");
    setError("");
    setProgress({ received: 0, total: info.zipSize });
    void (async () => {
      try {
        await downloadUpdate(info, { signal: ac.signal, onProgress: setProgress });
        if (!aliveRef.current) return;
        setPhase("applying");
        await applyUpdate(info);
      } catch (err) {
        if (!aliveRef.current || ac.signal.aborted) return;
        setPhase("error");
        setError(err instanceof Error ? err.message : String(err));
      }
    })();
  };

  const handleCancel = (): void => {
    abortRef.current?.abort();
    abortRef.current = null;
    void discardUpdate();
    setPhase("idle");
  };

  const handleSkip = (): void => {
    void skipVersion(info.latest);
    setInfo(null);
  };

  const handleLater = (): void => {
    setInfo(null);
  };

  const percent =
    progress.total > 0 ? Math.min(100, Math.floor((progress.received / progress.total) * 100)) : 0;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="updater-banner"
      className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-body-sm"
    >
      <span data-testid="updater-text">
        {phase === "downloading"
          ? t("updater.downloading", { percent: String(percent) })
          : phase === "applying"
            ? t("updater.applying")
            : t("updater.message", { current: info.current, latest: info.latest })}
      </span>
      {phase === "downloading" && (
        <progress
          data-testid="updater-progress"
          value={progress.received}
          max={progress.total > 0 ? progress.total : undefined}
          className="h-1.5 w-28"
        />
      )}
      {phase === "error" && (
        <span data-testid="updater-error" className="text-destructive">
          {t("updater.error", { message: error })}
        </span>
      )}
      {(phase === "idle" || phase === "error") && (
        <>
          <button
            type="button"
            data-testid="updater-install"
            onClick={handleInstall}
            className="rounded-md bg-accent px-3 py-1.5 font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {info.zipUrl ? t("updater.install") : t("updater.download")}
          </button>
          <button
            type="button"
            data-testid="updater-skip"
            onClick={handleSkip}
            className="rounded-md border bg-card px-3 py-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("updater.skip")}
          </button>
          <button
            type="button"
            data-testid="updater-later"
            onClick={handleLater}
            className="rounded-md border bg-card px-3 py-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("updater.later")}
          </button>
        </>
      )}
      {phase === "downloading" && (
        <button
          type="button"
          data-testid="updater-cancel"
          onClick={handleCancel}
          className="rounded-md border bg-card px-3 py-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("updater.cancel")}
        </button>
      )}
    </div>
  );
}
