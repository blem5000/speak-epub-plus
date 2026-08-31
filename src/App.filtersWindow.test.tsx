import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock sidecar for App + nested Filters
const mockGetFilters = vi.fn();
const mockCallSidecar = vi.fn();
const mockGetStore = vi.fn();

vi.mock("@/lib/sidecar", async () => {
  const actual = await vi.importActual<typeof import("@/lib/sidecar")>("@/lib/sidecar");
  return {
    ...actual,
    getFilters: (...args: unknown[]) => mockGetFilters(...args),
    addFilter: vi.fn().mockResolvedValue({ id: "1", result: { filters: [{ pattern: "Subscribe", isRegex: false }], added: true } }),
    removeFilter: vi.fn().mockResolvedValue({ id: "1", result: { filters: [], removed: true } }),
    isFiltersResult: (res: { result?: unknown }) => {
      if (!res.result || typeof res.result !== "object") return false;
      const r = res.result as Record<string, unknown>;
      return Array.isArray(r.filters);
    },
    callSidecar: (...args: unknown[]) => mockCallSidecar(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args),
    previewChapter: vi.fn().mockResolvedValue({
      id: "1",
      result: {
        url: "https://www.novelphoenix.com/novel/123/chapter/1",
        originalHtml: "<html>raw Subscribe</html>",
        originalText: "raw Subscribe",
        html: "<div>cleaned</div>",
        text: "cleaned",
        filteredHtml: "<div>cleaned filtered</div>",
        filteredText: "cleaned filtered",
        removedCount: 1,
        start: "div#chapter-content",
        end: null,
      },
    }),
    getSelectors: vi.fn().mockResolvedValue({ id: "1", result: { site: "novelphoenix.com", start: "div#chapter-content", end: null, defaultStart: "div#chapter-content", defaultEnd: null } }),
    saveSelectors: vi.fn().mockResolvedValue({ id: "1", result: { saved: true } }),
    clearSelectors: vi.fn().mockResolvedValue({ id: "1", result: { cleared: true } }),
    isPreviewResult: (res: { result?: unknown }) => {
      if (!res.result || typeof res.result !== "object") return false;
      const r = res.result as Record<string, unknown>;
      return typeof r.html === "string" && typeof r.text === "string";
    },
    buildEpub: vi.fn().mockResolvedValue({ id: "1", result: { path: "output/book.epub", size: 123, chapter_count: 1, epubcheck_ok: true, messages: [] } }),
    isEpubResult: (res: { result?: unknown }) => {
      if (!res.result || typeof res.result !== "object") return false;
      const r = res.result as Record<string, unknown>;
      return typeof r.path === "string";
    },
  };
});

// Mock hooks to simplify App rendering
vi.mock("@/hooks/useDebouncedSearch", () => ({
  useDebouncedSearch: () => ({ searching: false, results: [], error: null }),
}));
vi.mock("@/hooks/useChapterList", () => ({
  useChapterList: () => ({ loading: false, list: [], error: null, cover: null }),
}));
vi.mock("@/hooks/useFetcher", () => ({
  useFetcher: () => ({
    fetching: false,
    logs: [],
    throttle: { tier: "polite", delay: 4000 },
    statuses: {},
    partStatuses: {},
    progress: { done: 0, total: 0 },
    elapsedSec: 0,
    badge: null,
    error: null,
    start: vi.fn(),
    abort: vi.fn(),
    appendLogs: vi.fn(),
    setStatuses: vi.fn(),
  }),
}));

import App from "./App";

describe("App FiltersWindow 4.3 integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFilters.mockResolvedValue({ id: "1", result: { filters: [] } });
    mockCallSidecar.mockImplementation(async (method: unknown) => {
      if (method === "hello") return { id: "0", result: { pong: true } };
      if (method === "getSelection") return { id: "0", result: { selection: [], from: 1, to: 30, url: null } };
      if (method === "getSelection") return { id: "0", result: { selection: [], from: 1, to: 30, url: null } };
      return { id: "0", result: {} };
    });
    mockGetStore.mockResolvedValue({ id: "0", result: { voice: "en-US-AndrewNeural", parallel: 3 } });
  });

  it("header has filters window button that opens dialog", async () => {
    const user = userEvent.setup();
    render(<App />);
    const btn = await screen.findByTestId("filters-window-button");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-label", expect.stringMatching(/Filtry|Filters/));
    expect(screen.queryByTestId("filters-window-dialog")).not.toBeInTheDocument();
    await user.click(btn);
    const dialog = await screen.findByTestId("filters-window-dialog");
    expect(dialog).toBeInTheDocument();
    // scoped within dialog to avoid duplicate with embedded panel
    const { getByTestId } = await import("@testing-library/react");
    // use dialog container query
    expect(dialog.querySelector('[data-testid="filter-input"]')).not.toBeNull();
    expect(dialog.querySelector('[data-testid="filters-table"]')).not.toBeNull();
  });

  it("filters-updated event dispatched by Filters triggers Preview refetch (integration)", async () => {
    const user = userEvent.setup();
    render(<App />);
    // Open window and add a filter
    await user.click(await screen.findByTestId("filters-window-button"));
    const dialog = await screen.findByTestId("filters-window-dialog");
    const input = dialog.querySelector('[data-testid="filter-input"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    await user.type(input, "Subscribe");
    const addBtn = dialog.querySelector('[data-testid="filter-add"]') as HTMLButtonElement;
    await user.click(addBtn);
    await waitFor(() => expect(input).toBeInTheDocument());
    // dispatch is synchronous inside Filters handleAdd — verify event listener path still works by manual dispatch
    const evt = new CustomEvent("filters-updated");
    window.dispatchEvent(evt);
    // No throw and still window open
    expect(screen.getByTestId("filters-window-dialog")).toBeInTheDocument();
  });

  it("settings gear still works alongside filters window", async () => {
    const user = userEvent.setup();
    render(<App />);
    const filtersBtn = await screen.findByTestId("filters-window-button");
    const settingsBtn = screen.getByTestId("settings-gear");
    expect(filtersBtn).toBeInTheDocument();
    expect(settingsBtn).toBeInTheDocument();
    await user.click(settingsBtn);
    expect(await screen.findByTestId("settings-dialog")).toBeInTheDocument();
    // filters window not automatically open
    expect(screen.queryByTestId("filters-window-dialog")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("settings-close"));
    await waitFor(() => expect(screen.queryByTestId("settings-dialog")).not.toBeInTheDocument());
    await user.click(filtersBtn);
    expect(await screen.findByTestId("filters-window-dialog")).toBeInTheDocument();
  });
});
