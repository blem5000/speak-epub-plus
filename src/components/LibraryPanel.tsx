import { t } from "@/i18n";

export type LibraryEntry = {
  id: string;
  title: string;
  author: string;
  cover: string;
  path: string;
  format: string;
  size: number;
  chapters: number;
  sourceUrl: string;
  createdAt: number;
};

type LibraryPanelProps = {
  entries: LibraryEntry[];
  onOpen: (path: string) => void;
  onRemove: (path: string) => void;
};

function humanSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / (1024 * 1024))} MB`;
  return `${Math.round(bytes / 1024)} kB`;
}

/**
 * The audiobooks that were produced — with the cover, so the library is
 * browsable at a glance. Removing an entry only forgets it; the file on
 * disk is never deleted.
 */
export default function LibraryPanel({
  entries,
  onOpen,
  onRemove,
}: LibraryPanelProps): JSX.Element | null {
  if (entries.length === 0) return null;
  return (
    <section
      className="mt-6 rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("library.title") as string}
      data-testid="library-panel"
    >
      <h2 className="text-heading font-semibold">
        {t("library.title") as string} ({entries.length})
      </h2>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {entries.map((entry) => (
          <li
            key={entry.path}
            data-testid={`library-item-${entry.path}`}
            className="flex items-center gap-3 rounded-md border bg-muted/40 p-3"
          >
            {entry.cover ? (
              <img
                src={entry.cover}
                alt=""
                className="h-16 w-11 shrink-0 rounded object-cover border"
                loading="lazy"
              />
            ) : (
              <div
                className="h-16 w-11 shrink-0 rounded border bg-muted"
                aria-hidden="true"
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-body font-medium" title={entry.title}>
                {entry.title}
              </p>
              {entry.author ? (
                <p className="truncate text-body-xs text-muted-foreground">{entry.author}</p>
              ) : null}
              <p className="text-body-xs text-muted-foreground">
                {[
                  entry.format ? entry.format.toUpperCase() : null,
                  humanSize(entry.size),
                  entry.chapters ? t("library.chapters", { count: entry.chapters }) : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  data-testid={`library-open-${entry.path}`}
                  onClick={() => onOpen(entry.path)}
                  className="rounded-md border border-input bg-card px-2 py-0.5 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("library.open") as string}
                </button>
                <button
                  type="button"
                  data-testid={`library-remove-${entry.path}`}
                  onClick={() => onRemove(entry.path)}
                  title={t("library.removeTitle") as string}
                  className="rounded-md border border-input bg-card px-2 py-0.5 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("library.remove") as string}
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
