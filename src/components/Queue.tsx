import { useEffect, useRef, useState } from "react";
import type { ChapterInfo } from "@/hooks/useChapterList";
import type { PartStatusEvent } from "@/lib/sidecar";
import ThrottleBadge from "./ThrottleBadge";
import ProgressTrack from "./ProgressTrack";
import { t } from "@/i18n";

type QueueProps = {
  chapterList: ChapterInfo[];
  statuses: Record<number, string>;
  partStatuses: Record<string, PartStatusEvent>;
  progress: { done: number; total: number; percent: number };
  throttle: { tier: string; delay: number } | null;
  badge: string | null;
  logs: string[];
  fetching?: boolean;
  elapsedSec?: number;
  onAbort?: () => void;
};

export default function Queue({
  chapterList,
  statuses,
  partStatuses,
  progress,
  throttle,
  badge,
  logs,
  fetching,
  elapsedSec,
  onAbort,
}: QueueProps): JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggleExpand = (ch: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(ch)) next.delete(ch);
      else next.add(ch);
      return next;
    });
  };

  // auto-scroll to live row (fetching) — respects prefers-reduced-motion
  useEffect(() => {
    if (!listRef.current) return;
    // find first fetching chapter
    const liveIdx = chapterList.find((ch) => statuses[ch.index] === "fetching")?.index;
    if (liveIdx != null) {
      const el = listRef.current.querySelector(`[data-testid="queue-row-${liveIdx}"]`) as HTMLElement | null;
      if (el && typeof el.scrollIntoView === "function") {
        try {
          const prefersReduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
          el.scrollIntoView({ block: "nearest", behavior: prefersReduced ? "auto" : "smooth" });
        } catch {
          // ignore jsdom missing
        }
      }
    }
  }, [statuses, chapterList]);

  // group partStatuses by chapter
  const partsByChapter = new Map<number, PartStatusEvent[]>();
  Object.values(partStatuses).forEach((ps) => {
    const arr = partsByChapter.get(ps.chapter_number) ?? [];
    arr.push(ps);
    partsByChapter.set(ps.chapter_number, arr);
  });
  partsByChapter.forEach((arr) => arr.sort((a, b) => a.part_number - b.part_number));

  const N = chapterList.length;

  return (
    <section
      className="rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("queue.title") ?? "Queue"}
      data-testid="queue-section"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h2 className="text-heading font-semibold">{t("queue.title")}</h2>
          {elapsedSec != null && fetching ? (
            <span data-testid="elapsed" className="text-body-sm text-muted-foreground">
              {elapsedSec}s
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <ThrottleBadge throttle={throttle} />
          {badge ? (
            <span data-testid="resume-badge" className="rounded-full bg-accent/10 px-3 py-1 text-body-sm text-accent-foreground">
              {badge}
            </span>
          ) : null}
          {onAbort && fetching ? (
            <button
              type="button"
              data-testid="fetch-abort"
              onClick={onAbort}
              className="rounded-md border bg-card px-3 py-1 text-body-sm hover:bg-muted"
            >
              {t("queue.stop")}
            </button>
          ) : null}
        </div>
      </div>

      {progress && progress.total > 0 ? (
        <div className="mt-4">
          <div className="flex items-center justify-between text-body-sm text-muted-foreground">
            <span data-testid="progress-label">
              {progress.done}/{progress.total} ({progress.percent}%)
            </span>
          </div>
          <ProgressTrack done={progress.done} total={progress.total} />
        </div>
      ) : null}

      {N > 0 ? (
        <div ref={listRef} className="mt-4 space-y-1 max-h-80 overflow-auto" data-testid="queue-list">
          {chapterList.map((ch) => {
            const st = (statuses[ch.index] ?? "queued") as string;
            const parts = partsByChapter.get(ch.index) ?? [];
            const isExpanded = expanded.has(ch.index);
            // per-chapter progress: done parts / part_count
            const chDone = parts.filter((p) => p.status === "done" || p.status === "skipped").length;
            const chTotal = parts.length > 0 ? Math.max(...parts.map((p) => p.part_count)) : 0;
            const showProgress = chTotal > 0;
            return (
              <div
                key={ch.index}
                data-testid={`queue-row-${ch.index}`}
                className="flex flex-col gap-1 rounded-md border border-transparent px-2 py-1 hover:bg-muted/50"
              >
                <div className="flex items-center gap-2 text-body-sm">
                  <span
                    data-testid={`queue-pill-${ch.index}`}
                    className={
                      "rounded-full border px-2 py-0.5 text-mono text-xs " +
                      (st === "done"
                        ? "bg-success/10 text-success border-success/20"
                        : st === "error"
                          ? "bg-destructive/10 text-destructive border-destructive/20"
                          : st === "fetching"
                            ? "bg-accent/10 text-accent border-accent/20"
                            : st === "cleaning"
                              ? "bg-info/10 text-info border-info/20"
                              : st === "skipped"
                                ? "bg-success/10 text-success border-success/20"
                                : "bg-muted text-muted-foreground border-transparent")
                    }
                    aria-label={`chapter ${ch.index} ${st}`}
                  >
                    {st === "cleaning" ? "🧹 " : ""}
                    {st === "fetching" ? "⏳ " : ""}
                    {st === "done" ? "✓ " : ""}
                    {st === "error" ? "✗ " : ""}
                    {st === "skipped" ? "✓ " : ""}
                    {st}
                  </span>
                  <span className="truncate">
                    {ch.index}. {ch.title}
                  </span>
                  {parts.length > 0 ? (
                    <button
                      type="button"
                      data-testid={`queue-expand-${ch.index}`}
                      onClick={() => toggleExpand(ch.index)}
                      className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                    >
                      {isExpanded ? "▾" : "▸"} {parts.length} parts
                    </button>
                  ) : null}
                </div>
                {showProgress ? (
                  <div className="ml-16 flex items-center gap-2">
                    <ProgressTrack done={chDone} total={chTotal} />
                    <span className="text-xs text-muted-foreground">
                      {chDone}/{chTotal}
                    </span>
                  </div>
                ) : null}
                {isExpanded && parts.length > 0 ? (
                  <div className="ml-16 flex flex-wrap gap-1" data-testid={`queue-dots-${ch.index}`}>
                    {parts.map((p) => (
                      <span
                        key={`${p.chapter_number}-${p.part_number}`}
                        data-testid={`part-dot-${p.chapter_number}-${p.part_number}`}
                        title={`part ${p.part_number}/${p.part_count} ${p.status}`}
                        className={
                          "inline-block h-2 w-2 rounded-full " +
                          (p.status === "done"
                            ? "bg-success"
                            : p.status === "skipped"
                              ? "bg-success/50"
                              : p.status === "fetching"
                                ? "bg-accent animate-pulse"
                                : p.status === "error"
                                  ? "bg-destructive"
                                  : "bg-muted-foreground")
                        }
                        aria-label={`part ${p.part_number} ${p.status}`}
                      />
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-4 text-body-sm text-muted-foreground">—</div>
      )}

      <div
        role="log"
        aria-live="polite"
        aria-busy={!!fetching}
        aria-label="Log pobierania"
        data-testid="log-pane"
        className="mt-4 max-h-40 overflow-auto rounded-md border bg-muted p-3 mono text-mono text-body-sm"
      >
        {(logs ?? []).length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          (logs ?? []).slice(-200).map((line, i) => (
            <div key={i} data-testid="log-line">
              {line}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
