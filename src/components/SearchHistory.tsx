import { t } from "@/i18n";

export type SearchHistoryEntry = {
  query: string;
  at: number;
};

type SearchHistoryProps = {
  entries: SearchHistoryEntry[];
  onPick: (query: string) => void;
  onClear: () => void;
};

/**
 * The recent searches — clicking one runs it again. The history is kept
 * per user by the backend (search-history.json), not in the browser.
 */
export default function SearchHistory({
  entries,
  onPick,
  onClear,
}: SearchHistoryProps): JSX.Element | null {
  if (entries.length === 0) return null;
  return (
    <div className="mt-3" data-testid="search-history">
      <div className="flex items-center justify-between gap-2">
        <span className="text-body-sm text-muted-foreground">
          {t("history.title") as string}
        </span>
        <button
          type="button"
          data-testid="search-history-clear"
          onClick={onClear}
          className="rounded-md border border-input bg-card px-2 py-0.5 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("history.clear") as string}
        </button>
      </div>
      <ul className="mt-2 flex flex-wrap gap-2">
        {entries.map((entry) => (
          <li key={entry.query}>
            <button
              type="button"
              data-testid={`search-history-${entry.query}`}
              onClick={() => onPick(entry.query)}
              className="max-w-[240px] truncate rounded-full border border-input bg-card px-3 py-1 text-body-xs hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {entry.query}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
