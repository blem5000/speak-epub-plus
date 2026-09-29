import { useEffect, useState } from "react";
import { t } from "@/i18n";
import {
  checkForUpdates,
  dismissVersion,
  getCurrentVersion,
  isDismissed,
  openReleaseUrl,
  type UpdateInfo,
} from "@/lib/updater";

/** Startup update check — silent unless a newer GitHub Release exists. */
export default function UpdaterBanner(): JSX.Element | null {
  const [info, setInfo] = useState<UpdateInfo | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const current = await getCurrentVersion();
        if (!alive || !current) return;
        const found = await checkForUpdates(current);
        if (!alive || !found || !found.available) return;
        if (isDismissed(found.latest)) return;
        setInfo(found);
      } catch {
        // silent — update check never blocks startup
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!info) return null;

  const handleDownload = (): void => {
    void openReleaseUrl(info.url);
  };
  const handleDismiss = (): void => {
    dismissVersion(info.latest);
    setInfo(null);
  };

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="updater-banner"
      className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-body-sm"
    >
      <span data-testid="updater-text">
        {t("updater.message", { current: info.current, latest: info.latest })}
      </span>
      <button
        type="button"
        data-testid="updater-download"
        onClick={handleDownload}
        className="rounded-md bg-accent px-3 py-1.5 font-medium text-accent-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("updater.download")}
      </button>
      <button
        type="button"
        data-testid="updater-dismiss"
        onClick={handleDismiss}
        className="rounded-md border bg-card px-3 py-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("updater.later")}
      </button>
    </div>
  );
}
