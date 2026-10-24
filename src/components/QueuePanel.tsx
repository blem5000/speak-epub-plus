import { t } from "@/i18n";

export type QueueItem = {
  url: string;
  title: string;
  cover?: string | null;
};

export type QueueOutcome = {
  url: string;
  title: string;
  status: "ok" | "error";
  message?: string;
  path?: string;
};

type QueuePanelProps = {
  items: QueueItem[];
  outcomes: QueueOutcome[];
  running: boolean;
  progress: { index: number; total: number; title: string } | null;
  onRemove: (url: string) => void;
  onClear: () => void;
  onConvert: () => void;
  /** Stop the running batch; the in-flight book is cancelled too. */
  onStop?: () => void;
};

/**
 * The batch queue: several novels converted one after another. The backend
 * is driven one book at a time (list chapters → fetch → build), so a failure
 * of one book never stops the rest.
 */
export default function QueuePanel({
  items,
  outcomes,
  running,
  progress,
  onRemove,
  onClear,
  onConvert,
  onStop,
}: QueuePanelProps): JSX.Element | null {
  if (items.length === 0 && outcomes.length === 0) return null;

  const outcomeOf = (url: string): QueueOutcome | undefined =>
    outcomes.find((o) => o.url === url);

  return (
    <section
      className="mt-6 rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("queue.title") as string}
      data-testid="queue-panel"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-heading font-semibold">
          {t("queue.title") as string}
          {items.length > 0 ? ` (${items.length})` : ""}
        </h2>
        <div className="flex items-center gap-2">
          {items.length > 0 && !running ? (
            <button
              type="button"
              data-testid="queue-clear"
              onClick={onClear}
              className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("queue.clear") as string}
            </button>
          ) : null}
          <button
            type="button"
            data-testid="queue-convert"
            disabled={running || items.length === 0}
            onClick={onConvert}
            className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
          >
            {running ? (t("queue.running") as string) : (t("queue.convert") as string)}
          </button>
          {running && onStop ? (
            <button
              type="button"
              data-testid="queue-stop"
              onClick={onStop}
              className="h-9 rounded-md border border-destructive/40 bg-card px-3 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("queue.stop") as string}
            </button>
          ) : null}
        </div>
      </div>

      {progress ? (
        <p
          className="mt-3 text-body-sm text-muted-foreground"
          role="status"
          aria-live="polite"
          data-testid="queue-progress"
        >
          {t("queue.progress", {
            index: progress.index,
            total: progress.total,
            title: progress.title,
          }) as string}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className="mt-3 space-y-1" data-testid="queue-items">
          {items.map((item) => {
            const outcome = outcomeOf(item.url);
            return (
              <li
                key={item.url}
                className="flex items-center justify-between gap-3 text-body-sm"
                data-testid={`queue-item-${item.url}`}
              >
                <span className="min-w-0 flex-1 truncate">{item.title || item.url}</span>
                {outcome ? (
                  <span
                    className={
                      outcome.status === "ok"
                        ? "shrink-0 text-xs text-muted-foreground"
                        : "shrink-0 text-xs text-destructive"
                    }
                    data-testid={`queue-status-${item.url}`}
                  >
                    {outcome.status === "ok"
                      ? (t("queue.ok") as string)
                      : `${t("queue.failed") as string}: ${outcome.message ?? ""}`}
                  </span>
                ) : null}
                <button
                  type="button"
                  data-testid={`queue-remove-${item.url}`}
                  disabled={running}
                  onClick={() => onRemove(item.url)}
                  aria-label={t("queue.remove", { title: item.title || item.url }) as string}
                  className="shrink-0 rounded-md border border-input bg-card px-2 py-0.5 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {t("queue.removeShort") as string}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}

      {outcomes.filter((o) => o.status === "ok" && o.path).length > 0 ? (
        <div className="mt-3 text-body-sm text-muted-foreground" data-testid="queue-outputs">
          {t("queue.done", {
            n: outcomes.filter((o) => o.status === "ok").length,
            failed: outcomes.filter((o) => o.status === "error").length,
          }) as string}
        </div>
      ) : null}
    </section>
  );
}
