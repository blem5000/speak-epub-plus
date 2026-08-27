import { useEffect, useRef, useState } from "react";
import { t } from "@/i18n";
import type { SearchResult } from "@/hooks/useDebouncedSearch";

type ResultsTableProps = {
  results: SearchResult[];
  selectedUrl: string | null;
  onSelect: (url: string) => void;
};

export default function ResultsTable({ results, selectedUrl, onSelect }: ResultsTableProps): JSX.Element | null {
  const [focusedIndex, setFocusedIndex] = useState(0);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);

  // Keep focusedIndex within bounds when results change
  useEffect(() => {
    if (focusedIndex >= results.length) setFocusedIndex(results.length > 0 ? results.length - 1 : 0);
  }, [results.length, focusedIndex]);

  // When focusedIndex changes, keep within bounds; focus moves explicitly on arrow keys
  useEffect(() => {
    if (focusedIndex >= results.length && results.length > 0) {
      setFocusedIndex(0);
    }
  }, [focusedIndex, results.length]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>, idx: number): void => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min(idx + 1, results.length - 1);
      setFocusedIndex(next);
      rowRefs.current[next]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = Math.max(idx - 1, 0);
      setFocusedIndex(prev);
      rowRefs.current[prev]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      setFocusedIndex(0);
      rowRefs.current[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      const last = results.length - 1;
      setFocusedIndex(last);
      rowRefs.current[last]?.focus();
    } else if (e.key === "Enter" || e.key === " ") {
      // Enter Wybierz, Space toggle — for Find, both select
      e.preventDefault();
      const r = results[idx];
      if (r?.url) onSelect(r.url);
    }
  };

  if (results.length === 0) return null;

  return (
    <div
      className="overflow-hidden rounded-lg border bg-card"
      role="region"
      aria-label={t("results.region") ?? "Search results"}
    >
      <div className="max-h-[320px] overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 border-b bg-card backdrop-blur supports-[backdrop-filter]:bg-card/95">
            <tr className="text-body-sm text-muted-foreground">
              <th className="px-4 py-2 font-semibold">{t("results.headers.site")}</th>
              <th className="px-4 py-2 font-semibold">{t("results.headers.title")}</th>
              <th className="px-4 py-2 font-semibold">{t("results.headers.chapters")}</th>
              <th className="px-4 py-2 font-semibold">{t("results.headers.link")}</th>
            </tr>
          </thead>
          <tbody className="text-body">
            {results.map((r, idx) => {
              const isSelected = selectedUrl === r.url;
              const isFocused = focusedIndex === idx;
              return (
                <tr
                  key={(r.url || r.link || "") + idx}
                  ref={(el) => {
                    rowRefs.current[idx] = el;
                  }}
                  role="button"
                  tabIndex={isFocused ? 0 : -1}
                  aria-selected={isSelected}
                  onClick={() => {
                    if (r?.url) onSelect(r.url);
                  }}
                  onKeyDown={(e) => handleKeyDown(e, idx)}
                  onFocus={() => setFocusedIndex(idx)}
                  className={
                    "cursor-pointer border-b last:border-b-0 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset " +
                    (isSelected
                      ? "border-l-2 border-accent bg-[#EFF3FF] "
                      : "border-l-2 border-transparent hover:bg-muted ") +
                    " "
                  }
                  // AA ring 2px handled via focus-visible:ring-2
                >
                  <td className="px-4 py-2.5 text-body-sm">{r.site || "—"}</td>
                  <td className="px-4 py-2.5 font-medium">{r.title}</td>
                  <td className="px-4 py-2.5 text-body-sm">{r.chapters ?? r.chapter_count ?? "—"}</td>
                  <td className="max-w-[220px] truncate px-4 py-2.5 text-body-sm text-muted-foreground">
                    <a
                      href={r.link || r.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="underline decoration-border underline-offset-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      tabIndex={-1}
                    >
                      {r.link || r.url}
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
