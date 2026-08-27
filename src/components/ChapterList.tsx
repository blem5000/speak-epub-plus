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
  onSelectedChange: (next: Set<number>) => void;
  onRangeChange: (from: number, to: number) => void;
  onAnchorChange: (anchor: number | null) => void;
  onPreview?: (index: number) => void;
};

export default function ChapterList({
  chapters,
  selected,
  from,
  to,
  anchor,
  onSelectedChange,
  onRangeChange,
  onAnchorChange,
  onPreview,
}: ChapterListProps): JSX.Element {
  const N = chapters.length;
  const [focusedIndex, setFocusedIndex] = useState<number>(0);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);

  useEffect(() => {
    if (focusedIndex >= N) {
      setFocusedIndex(N > 0 ? N - 1 : 0);
    }
  }, [N, focusedIndex]);

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

  const handleSelectRange = (): void => {
    if (N === 0) return;
    // guard empty → no-op
    if (from === undefined || to === undefined) return;
    // non-numeric handled via rangeToSet returning empty
    const set = rangeToSet(from, to, N);
    if (set.size === 0) return;
    onSelectedChange(set);
    // update anchor to to after select? keep last range end
    const clampedFrom = clamp(Number(from), 1, N);
    const clampedTo = clamp(Number(to), 1, N);
    let a = clampedFrom;
    let b = clampedTo;
    if (a > b) [a, b] = [b, a];
    onAnchorChange(b);
    onRangeChange(a, b);
  };

  const handleClear = (): void => {
    onSelectedChange(new Set());
    onAnchorChange(null);
  };

  const handleKeyDownRow = (e: React.KeyboardEvent<HTMLTableRowElement>, rowPos: number, chapterIdx: number): void => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min(rowPos + 1, N - 1);
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
      const last = N - 1;
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

  // virtualized fallback warning
  const isVirtualized = N > 500;

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
        <RangeBar
          from={from}
          to={to}
          total={total}
          selectedCount={selectedCount}
          onChangeRange={onRangeChange}
          onSelectRange={handleSelectRange}
          onClear={handleClear}
        />
      </div>

      {isVirtualized ? (
        <div className="bg-warning/10 px-4 py-2 text-body-sm text-warning" data-testid="virtualized-warning">
          Virtualized fallback: showing all {N} rows (windowing deferred)
        </div>
      ) : null}

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
            {chapters.map((ch, arrIdx) => {
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
                    const withShift = (e as React.MouseEvent).shiftKey;
                    handleToggle(idx, withShift);
                  }}
                  onDoubleClick={() => {
                    if (onPreview) onPreview(idx);
                    else if (import.meta.env.DEV) console.debug(`Preview placeholder for chapter ${idx}`);
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
                      className="ml-2 hidden text-muted-foreground group-hover:inline"
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
    </div>
  );
}
