import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { t } from "@/i18n";

type RuntimeProgress = { received: number; total: number };

/**
 * First-launch banner: the Python runtime tier is downloaded once (~60 MB)
 * and cached in the user profile. Without this the app looks frozen while the
 * sidecar waits for the interpreter.
 */
export default function RuntimeBanner(): JSX.Element | null {
  const [progress, setProgress] = useState<RuntimeProgress | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let unlistenProgress: (() => void) | null = null;
    let unlistenReady: (() => void) | null = null;
    let cancelled = false;
    void (async () => {
      try {
        unlistenProgress = await listen<RuntimeProgress>("runtimeDownloadProgress", (e) => {
          if (!cancelled) setProgress(e.payload);
        });
        unlistenReady = await listen("runtimeReady", () => {
          if (!cancelled) setReady(true);
        });
      } catch {
        // no Tauri runtime (dev server) -> nothing to show
      }
    })();
    return () => {
      cancelled = true;
      unlistenProgress?.();
      unlistenReady?.();
    };
  }, []);

  if (!progress || ready) return null;

  const total = progress.total > 0 ? progress.total : 0;
  const percent = total > 0 ? Math.min(100, Math.round((progress.received / total) * 100)) : 0;
  const downloading = total === 0 || progress.received < total;

  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-body-sm"
      role="status"
      aria-live="polite"
      data-testid="runtime-banner"
    >
      <span>{downloading ? t("runtime.download", { percent: String(percent) }) : t("runtime.preparing")}</span>
      {downloading && (
        <progress
          className="h-1.5 w-28"
          max={100}
          value={percent}
          data-testid="runtime-progress"
        />
      )}
    </div>
  );
}
