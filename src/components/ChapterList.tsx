import { useEffect, useRef, useState } from "react";
import { t } from "@/i18n";
import type { ChapterInfo } from "@/hooks/useChapterList";
import RangeBar from "./RangeBar";
import { bulkShift, clamp, rangeToSet } from "@/lib/selection";

type ChapterListProps = {
  chapters: ChapterInfo[];
  selected: Set<number>;
  from: number;
  to: number;
  anchor: number | null;
  busy: boolean;
  onSelectedChange: (next: Set<number>) => void;
  onRangeChange: (from: number, to: number) => void;
  onAnchorChange: (anchor: number | null) => void;
  onStartFetch: (from: number, to: number) => void;
  onPreview?: (index: number) => void;
  /** Advanced mode: the range fields + Start live in the wizard above, so the
   *  embedded RangeBar is hidden; the detail table + expand toggle stay. */
  hideRangeBar?: boolean;
};

export default function ChapterList({
  chapters,
  selected,
  from,
  to,
  anchor,
  busy,
  onSelectedChange,
  onRangeChange,
  onAnchorChange,
  onStartFetch,
  onPreview,
  hideRangeBar = false,
}: ChapterListProps): JSX.Element {
  const N = chapters.length;
  const [focusedIndex, setFocusedIndex] = useState<number>(0);
  const [showAll, setShowAll] = useState(false);
  // The list itself is rarely used (ranges are typed, not clicked) —
  // keep it collapsed by default, RangeBar stays visible.
  const [expanded, setExpanded] = useState(false);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  // a long book renders in blocks: "Show all" would freeze the GUI with
  // 800+ rows, so the list grows in steps instead
  const ROW_BLOCK = 100;
  const [visibleLimit, setVisibleLimit] = useState(ROW_BLOCK);
  const displayChapters =
    N > 500 ? chapters.slice(0, showAll ? Math.max(ROW_BLOCK, visibleLimit) : ROW_BLOCK) : chapters;

  useEffect(() => {
    const len = displayChapters.length;
    if (focusedIndex >= len) {
      setFocusedIndex(len > 0 ? len - 1 : 0);
    }
  }, [displayChapters.length, focusedIndex]);

  const isSelected = (idx: number): boolean => selected.has(idx);

  const handleToggle = (idx: number, withShift: boolean): void => {
    if (withShift && anchor != null) {
      const next = bulkShift(anchor, idx, selected);
      onSelectedChange(next);
      // anchor stays
    } else {
      const next = new Set(selected);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      onSelectedChange(next);
      onAnchorChange(idx);
    }
  };

  const handleStartRange = (rangeFrom: number, rangeTo: number): void => {
    if (N === 0) return;
    // Use the explicitly committed field values (never stale parent props).
    const set = rangeToSet(rangeFrom, rangeTo, N);
    if (set.size === 0) return;
    onSelectedChange(set);
    // update anchor to to after select? keep last range end
    const clampedFrom = clamp(Number(rangeFrom), 1, N);
    const clampedTo = clamp(Number(rangeTo), 1, N);
    let a = clampedFrom;
    let b = clampedTo;
    if (a > b) [a, b] = [b, a];
    onAnchorChange(b);
    onRangeChange(a, b);
    onStartFetch(a, b);
  };

  const handleKeyDownRow = (e: React.KeyboardEvent<HTMLTableRowElement>, rowPos: number, chapterIdx: number): void => {
    const visibleLen = displayChapters.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min(rowPos + 1, visibleLen - 1);
      setFocusedIndex(next);
      rowRefs.current[next]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = Math.max(rowPos - 1, 0);
      setFocusedIndex(prev);
      rowRefs.current[prev]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      setFocusedIndex(0);
      rowRefs.current[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      const last = visibleLen - 1;
      setFocusedIndex(last);
      rowRefs.current[last]?.focus();
    } else if (e.key === " " || e.code === "Space") {
      e.preventDefault();
      const withShift = e.shiftKey;
      handleToggle(chapterIdx, withShift);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const withShift = e.shiftKey;
      handleToggle(chapterIdx, withShift);
    } else if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
      e.preventDefault();
      e.stopPropagation();
      const all = new Set<number>();
      for (let i = 1; i <= N; i++) all.add(i);
      onSelectedChange(all);
      onAnchorChange(1);
    } else if (e.key === "Escape") {
      e.stopPropagation();
    }
  };

  const handleSelectAllKey = (e: React.KeyboardEvent<HTMLDivElement>): void => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
      e.preventDefault();
      const all = new Set<number>();
      for (let i = 1; i <= N; i++) all.add(i);
      onSelectedChange(all);
      onAnchorChange(1);
    }
  };

  const total = N;
  const selectedCount = selected.size;

  // virtualized fallback warning — capped to 100 rows until react-window, with Show all to reveal rest
  const isVirtualized = N > 500;
  const showingAll = isVirtualized ? showAll : true;

  return (
    <div
      className="overflow-hidden rounded-lg border bg-card"
      role="region"
      aria-label={t("chapterList.title") ?? "Chapters"}
      onKeyDown={handleSelectAllKey}
      tabIndex={0}
      aria-roledescription="chapter list"
    >
      <div className="border-b bg-card px-4 py-3">
        {hideRangeBar ? null : (
          <RangeBar
            from={from}
            to={to}
            total={total}
            selectedCount={selectedCount}
            busy={busy}
            onChangeRange={onRangeChange}
            onStartRange={handleStartRange}
          />
        )}
        <button
          type="button"
          data-testid="chapter-list-toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-2 rounded-md border bg-card px-3 py-1 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? t("chapterList.collapse") : t("chapterList.expand", { total: N })}
        </button>
      </div>

      {expanded && isVirtualized ? (
        <div
          className="bg-warning/10 px-4 py-2 text-body-sm text-warning flex items-center justify-between gap-2"
          data-testid="virtualized-warning"
          role="alert"
          aria-live="polite"
        >
          <span>
            {showingAll
              ? `Showing ${displayChapters.length} of ${N} rows`
              : `Showing 100 of ${N} rows — windowing deferred`}
          </span>
          {displayChapters.length < N ? (
            <button
              type="button"
              onClick={() => {
                setShowAll(true);
                setVisibleLimit((prev) => prev + ROW_BLOCK);
              }}
              className="rounded-md border bg-card px-3 py-1 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="virtualized-show-all"
            >
              {displayChapters.length < N ? `Show more (${Math.min(ROW_BLOCK, N - displayChapters.length)} more)` : "Show all"}
            </button>
          ) : null}
        </div>
      ) : null}

      {expanded ? (
      <div className="max-h-[480px] overflow-auto" role="grid" aria-rowcount={N} aria-colcount={3}>
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 border-b bg-card backdrop-blur supports-[backdrop-filter]:bg-card/95">
            <tr className="h-9 text-body-sm text-muted-foreground">
              <th className="w-10 px-2 py-2 text-center font-semibold">
                <span aria-hidden="true">✓</span>
              </th>
              <th className="w-14 px-2 py-2 font-semibold">#</th>
              <th className="px-4 py-2 font-semibold">{t("chapterList.title")}</th>
            </tr>
          </thead>
          <tbody className="text-body" role="rowgroup">
            {displayChapters.map((ch, arrIdx) => {
              const idx = ch.index;
              const selectedRow = isSelected(idx);
              const rowPos = arrIdx; // use array order for roving, not idx-1
              const isFocused = focusedIndex === rowPos;
              return (
                <tr
                  key={`${ch.url}::${idx}::${arrIdx}`}
                  ref={(el) => {
                    rowRefs.current[rowPos] = el;
                  }}
                  role="row"
                  tabIndex={isFocused ? 0 : -1}
                  aria-selected={selectedRow}
                  data-index={idx}
                  data-selected={selectedRow}
                  data-testid={`chapter-row-${idx}`}
                  onClick={(e) => {
                    // P18: ignore double/triple click to avoid toggle before preview
                    if ((e as React.MouseEvent).detail >= 2) return;
                    const withShift = (e as React.MouseEvent).shiftKey;
                    handleToggle(idx, withShift);
                  }}
                  onDoubleClick={(e) => {
                    e.stopPropagation();
                    if (onPreview) onPreview(idx);
                    // P15: no-op if onPreview null (remove console.debug leak)
                  }}
                  onKeyDown={(e) => handleKeyDownRow(e, rowPos, idx)}
                  onFocus={() => setFocusedIndex(rowPos)}
                  className={
                    "group h-9 cursor-pointer border-b last:border-b-0 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset " +
                    (selectedRow
                      ? "border-l-2 border-accent bg-accent/10 "
                      : "border-l-2 border-transparent hover:bg-muted ") +
                    " "
                  }
                  style={{ height: "36px" }}
                  aria-rowindex={arrIdx + 1}
                >
                  <td className="px-2 py-1 text-center">
                    <input
                      type="checkbox"
                      role="checkbox"
                      aria-checked={selectedRow}
                      aria-label={`Chapter ${idx}`}
                      checked={selectedRow}
                      onChange={() => {
                        // handled via row click; prevent double toggle but keep sync
                        // we still need to toggle if user clicks directly on checkbox
                        // use without shift for direct checkbox click
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        const withShift = (e as React.MouseEvent).shiftKey;
                        handleToggle(idx, withShift);
                      }}
                      className="h-4 w-4 rounded border-input accent-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      tabIndex={-1}
                    />
                  </td>
                  <td className="mono px-2 py-1 text-mono text-muted-foreground">{idx}</td>
                  <td className="px-4 py-1 text-body flex items-center justify-between">
                    <span className="truncate">{ch.title || "—"}</span>
                    <span
                      aria-hidden="true"
                      className="ml-2 hidden text-muted-foreground group-hover:inline group-focus:inline group-focus-within:inline focus-visible:inline"
                      title="Preview"
                    >
                      👁
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      ) : null}
    </div>
  );
}
