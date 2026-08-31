import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockGetFilters = vi.fn();
const mockCallSidecar = vi.fn();
const mockGetStore = vi.fn();
let throttleTier: string | null = "polite";
let logsMock: string[] = [];
let chapterErrorMock: string | null = null;
let fetcherErrorMock: string | null = null;
let chapterListMock: Array<{ index: number; title: string; url: string }> = [];
let progressMock = { done: 0, total: 0, percent: 0 };
let selectedMock = new Set<number>([1, 2, 3]);

vi.mock("@/lib/sidecar", async () => {
  const actual = await vi.importActual<typeof import("@/lib/sidecar")>("@/lib/sidecar");
  return {
    ...actual,
    getFilters: (...args: unknown[]) => mockGetFilters(...args),
    addFilter: vi.fn().mockResolvedValue({ id: "1", result: { filters: [], added: true } }),
    removeFilter: vi.fn().mockResolvedValue({ id: "1", result: { filters: [], removed: true } }),
    isFiltersResult: () => false,
    callSidecar: (...args: unknown[]) => mockCallSidecar(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args),
    previewChapter: vi.fn().mockResolvedValue({
      id: "1",
      result: { url: "", originalHtml: "", originalText: "", html: "<div>cleaned</div>", text: "cleaned", start: "div#chapter-content", end: null },
    }),
    getSelectors: vi.fn().mockResolvedValue({ id: "1", result: { site: "novelphoenix.com", start: "div#chapter-content", end: null, defaultStart: "div#chapter-content", defaultEnd: null } }),
    saveSelectors: vi.fn().mockResolvedValue({ id: "1", result: { saved: true } }),
    clearSelectors: vi.fn().mockResolvedValue({ id: "1", result: { cleared: true } }),
    isPreviewResult: () => false,
    buildEpub: vi.fn().mockResolvedValue({ id: "1", result: { path: "output/book.epub", size: 123, chapter_count: 1, epubcheck_ok: true, messages: [] } }),
    isEpubResult: () => false,
  };
});

vi.mock("@/hooks/useDebouncedSearch", () => ({
  useDebouncedSearch: () => ({ searching: false, results: [], error: null }),
}));

vi.mock("@/hooks/useChapterList", () => ({
  useChapterList: () => ({ loading: false, list: chapterListMock as unknown as ReturnType<typeof import("@/hooks/useChapterList").useChapterList>["list"], error: chapterErrorMock, cover: null }),
}));

vi.mock("@/hooks/useFetcher", () => ({
  useFetcher: () => ({
    fetching: false,
    logs: logsMock,
    throttle: throttleTier ? { tier: throttleTier, delay: throttleTier === "safe" ? 10000 : 4000 } : null,
    statuses: {},
    partStatuses: {},
    progress: progressMock,
    elapsedSec: 0,
    badge: null,
    error: fetcherErrorMock,
    start: vi.fn(),
    abort: vi.fn(),
    appendLogs: vi.fn(),
    setStatuses: vi.fn(),
  }),
}));

import App from "./App";

describe("App 4.4 — state treatments + a11y + platform", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFilters.mockResolvedValue({ id: "1", result: { filters: [] } });
    mockCallSidecar.mockImplementation(async (method: unknown) => {
      if (method === "hello") return { id: "0", result: { pong: true } };
      if (method === "getSelection") return { id: "0", result: { selection: Array.from(selectedMock), from: 1, to: 30, url: "https://www.novelphoenix.com/novel/123" } };
      return { id: "0", result: {} };
    });
    mockGetStore.mockResolvedValue({ id: "0", result: { voice: "en-US-AndrewNeural", parallel: 3 } });
    throttleTier = "polite";
    logsMock = [];
    chapterErrorMock = null;
    fetcherErrorMock = null;
    chapterListMock = Array.from({ length: 142 }, (_, i) => ({ index: i + 1, title: `Chapter ${i + 1}`, url: `https://www.novelphoenix.com/novel/123/chapter/${i + 1}` }));
    progressMock = { done: 5, total: 10, percent: 50 };
    selectedMock = new Set([1, 2, 3, 4, 5, 6]);
  });

  it("surface announcer live region renders Wyszukiwanie / Lista / Wybrano / Kolejka", async () => {
    render(<App />);
    const announcer = await screen.findByTestId("surface-announcer");
    expect(announcer).toHaveAttribute("aria-live", "polite");
    expect(announcer.textContent).toMatch(/Lista.*142|Chapters.*142|Wyszukiwanie/);
    expect(announcer.textContent).toMatch(/Wybrano|Kolejka|Selected|Queue/);
  });

  it("cold launch focus is in find input", async () => {
    render(<App />);
    const input = await screen.findByTestId("find-input");
    // jsdom autoFocus should place focus on input
    expect(document.activeElement).toBe(input);
  });

  it("throttle safe shows toast", async () => {
    throttleTier = "safe";
    render(<App />);
    expect(await screen.findByTestId("throttle-toast")).toBeInTheDocument();
    expect(screen.getByTestId("throttle-toast")).toHaveAttribute("role", "alert");
  });

  it("ban hint shows on LIST_FAILED", async () => {
    chapterErrorMock = "LIST_FAILED";
    render(<App />);
    expect(await screen.findByTestId("ban-hint")).toBeInTheDocument();
    expect(screen.getByTestId("ban-hint").textContent).toMatch(/Przerwa|Wznów/);
  });

  it("ffmpeg warning shows when logs contain ffmpeg", async () => {
    logsMock = ["checking ffmpeg -version", "ffmpeg not found"];
    render(<App />);
    expect(await screen.findByTestId("ffmpeg-warning")).toBeInTheDocument();
    expect(screen.getByTestId("ffmpeg-warning").textContent).toMatch(/FFmpeg nie znaleziono.*ffmpeg -version/);
  });

  it("header has data-tauri-drag-region", async () => {
    render(<App />);
    const header = document.querySelector("header[data-tauri-drag-region]");
    expect(header).not.toBeNull();
  });

  it("filters window button still present alongside announcer", async () => {
    render(<App />);
    expect(await screen.findByTestId("filters-window-button")).toBeInTheDocument();
    expect(await screen.findByTestId("surface-announcer")).toBeInTheDocument();
  });
});
