import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Queue from "./Queue";
import type { ChapterInfo } from "@/hooks/useChapterList";

function makeChapters(n: number): ChapterInfo[] {
  return Array.from({ length: n }, (_, i) => ({
    index: i + 1,
    title: `Chapter ${i + 1}`,
    url: `https://www.novelphoenix.com/novel/123/chapter/${i + 1}`,
  }));
}

describe("Queue live — per-chapter row + pill + mini progress + part dots + log cap + auto-scroll", () => {
  it("renders queue-section with per-chapter pills", () => {
    const chapters = makeChapters(3);
    const statuses = { 1: "queued", 2: "fetching", 3: "done" } as Record<number, string>;
    render(
      <Queue chapterList={chapters} statuses={statuses} partStatuses={{}} progress={{ done: 1, total: 3, percent: 33 }} throttle={{ tier: "polite", delay: 4000 }} badge={null} logs={[]} />
    );
    expect(screen.getByTestId("queue-section")).toBeInTheDocument();
    expect(screen.getByTestId("queue-list")).toBeInTheDocument();
    expect(screen.getByTestId("queue-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("queue-pill-1").textContent).toContain("queued");
    expect(screen.getByTestId("queue-pill-2").textContent).toContain("fetching");
    expect(screen.getByTestId("queue-pill-3").textContent).toContain("done");
  });

  it("shows throttle-badge safe and resume badge pominięto", () => {
    const chapters = makeChapters(2);
    render(
      <Queue
        chapterList={chapters}
        statuses={{}}
        partStatuses={{}}
        progress={{ done: 0, total: 2, percent: 0 }}
        throttle={{ tier: "safe", delay: 10000 }}
        badge="pominięto 20, pobieram 21–40"
        logs={[]}
      />
    );
    expect(screen.getByTestId("throttle-badge").textContent).toBe("safe 10000");
    expect(screen.getByTestId("resume-badge").textContent).toBe("pominięto 20, pobieram 21–40");
  });

  it("shows open-ended wykryto badge", () => {
    const chapters = makeChapters(1);
    render(
      <Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 0, percent: 0 }} throttle={{ tier: "polite", delay: 4000 }} badge="pominięto 100, wykryto 5 nowe" logs={[]} />
    );
    expect(screen.getByTestId("resume-badge").textContent).toContain("wykryto 5 nowe");
  });

  it("renders mini progress-track per chapter and global", () => {
    const partStatuses = {
      "40-1": { chapter_number: 40, part_number: 1, part_count: 3, is_final_chapter_file: false, status: "done" },
      "40-2": { chapter_number: 40, part_number: 2, part_count: 3, is_final_chapter_file: false, status: "fetching" },
      "40-3": { chapter_number: 40, part_number: 3, part_count: 3, is_final_chapter_file: false, status: "queued" },
    } as unknown as Record<string, import("@/lib/sidecar").PartStatusEvent>;
    // need chapter with index 40 to match parts
    const chapters40 = [{ index: 40, title: "C40", url: "https://www.novelphoenix.com/novel/123/chapter/40" } as ChapterInfo];
    render(
      <Queue chapterList={chapters40} statuses={{ 40: "fetching" }} partStatuses={partStatuses} progress={{ done: 1, total: 3, percent: 33 }} throttle={{ tier: "polite", delay: 4000 }} badge={null} logs={[]} />
    );
    // global progress-track
    expect(screen.getAllByTestId("progress-track").length).toBeGreaterThanOrEqual(1);
    // expand to see dots
    fireEvent.click(screen.getByTestId("queue-expand-40"));
    expect(screen.getByTestId("queue-dots-40")).toBeInTheDocument();
    expect(screen.getByTestId("part-dot-40-1")).toBeInTheDocument();
    expect(screen.getByTestId("part-dot-40-2")).toBeInTheDocument();
  });

  it("log cap slice(-200) shows only last 200", () => {
    const chapters = makeChapters(1);
    const logs = Array.from({ length: 250 }, (_, i) => `line ${i}`);
    render(<Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 0, percent: 0 }} throttle={{ tier: "polite", delay: 4000 }} badge={null} logs={logs} />);
    const lines = screen.getAllByTestId("log-line");
    expect(lines.length).toBe(200);
    expect(lines[0].textContent).toBe("line 50");
    expect(lines[199].textContent).toBe("line 249");
  });

  it("renders log pane role=log aria-live", () => {
    const chapters = makeChapters(1);
    render(<Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 0, percent: 0 }} throttle={null} badge={null} logs={["hello"]} />);
    const pane = screen.getByTestId("log-pane");
    expect(pane.getAttribute("role")).toBe("log");
    expect(pane.getAttribute("aria-live")).toBe("polite");
  });

  it("no 50 cap renders all 100 rows", () => {
    const chapters = makeChapters(100);
    render(<Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 100, percent: 0 }} throttle={null} badge={null} logs={[]} />);
    expect(screen.getAllByTestId(/queue-row-/).length).toBe(100);
  });

  it("auto-scroll to live row via scrollIntoView", () => {
    const chapters = makeChapters(5);
    const statuses = { 1: "done", 2: "done", 3: "fetching", 4: "queued", 5: "queued" } as Record<number, string>;
    // mock scrollIntoView
    const spy = vi.fn();
    // @ts-ignore patch prototype
    window.HTMLElement.prototype.scrollIntoView = spy;
    render(<Queue chapterList={chapters} statuses={statuses} partStatuses={{}} progress={{ done: 2, total: 5, percent: 40 }} throttle={{ tier: "polite", delay: 4000 }} badge={null} logs={[]} />);
    // after render, effect should have called scrollIntoView for row 3
    // wait a tick — effect runs sync after paint, but we can check spy called
    expect(spy).toHaveBeenCalled();
  });

  it("abort button when fetching", () => {
    const chapters = makeChapters(2);
    const onAbort = vi.fn();
    render(<Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 2, percent: 0 }} throttle={{ tier: "polite", delay: 4000 }} badge={null} logs={[]} fetching={true} onAbort={onAbort} />);
    const btn = screen.getByTestId("fetch-abort");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onAbort).toHaveBeenCalled();
  });

  it("elapsed shows when fetching", () => {
    const chapters = makeChapters(1);
    render(<Queue chapterList={chapters} statuses={{}} partStatuses={{}} progress={{ done: 0, total: 1, percent: 0 }} throttle={null} badge={null} logs={[]} fetching={true} elapsedSec={42} />);
    expect(screen.getByTestId("elapsed")).toBeInTheDocument();
    expect(screen.getByTestId("elapsed").textContent).toContain("42");
  });

  it("ETA appears from elapsed + partial progress, hidden at 0 or 100%", () => {
    const chapters = makeChapters(4);
    // half done after 10s -> ~10s remaining
    const { rerender } = render(
      <Queue chapterList={chapters} statuses={{} as Record<number, string>} partStatuses={{}} progress={{ done: 2, total: 4, percent: 50 }} throttle={null} badge={null} logs={[]} elapsedSec={10} />
    );
    const eta = screen.getByTestId("eta-label");
    expect(eta).toBeInTheDocument();
    expect(eta.textContent).toContain("10");

    // done==0: no basis to estimate — must be absent
    rerender(
      <Queue chapterList={chapters} statuses={{} as Record<number, string>} partStatuses={{}} progress={{ done: 0, total: 4, percent: 0 }} throttle={null} badge={null} logs={[]} elapsedSec={10} />
    );
    expect(screen.queryByTestId("eta-label")).not.toBeInTheDocument();

    // all done: ETA gone
    rerender(
      <Queue chapterList={chapters} statuses={{} as Record<number, string>} partStatuses={{}} progress={{ done: 4, total: 4, percent: 100 }} throttle={null} badge={null} logs={[]} elapsedSec={99} />
    );
    expect(screen.queryByTestId("eta-label")).not.toBeInTheDocument();

    // no elapsed yet: hidden even with partial progress
    rerender(
      <Queue chapterList={chapters} statuses={{} as Record<number, string>} partStatuses={{}} progress={{ done: 2, total: 4, percent: 50 }} throttle={null} badge={null} logs={[]} />
    );
    expect(screen.queryByTestId("eta-label")).not.toBeInTheDocument();
  });
});
