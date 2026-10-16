import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock sidecar for App + nested Filters/Settings
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
    setPartStatuses: vi.fn(),
  }),
}));

import App from "./App";

describe("App advanced panel integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFilters.mockResolvedValue({ id: "1", result: { filters: [] } });
    mockCallSidecar.mockImplementation(async (method: unknown) => {
      if (method === "hello") return { id: "0", result: { pong: true } };
      if (method === "getSelection") return { id: "0", result: { selection: [], from: 1, to: 30, url: null } };
      return { id: "0", result: {} };
    });
    mockGetStore.mockResolvedValue({ id: "0", result: { voice: "en-US-AndrewNeural", parallel: 3 } });
  });

  it("advanced panel is collapsed by default and expands on toggle", async () => {
    const user = userEvent.setup();
    render(<App />);
    const toggle = await screen.findByTestId("advanced-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("advanced-content")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(await screen.findByTestId("advanced-content")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-dialog")).not.toBeInTheDocument();
  });

  it("expanded panel hosts filters (input + table) and inline settings", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("advanced-toggle"));
    const content = await screen.findByTestId("advanced-content");
    await waitFor(() => {
      expect(content.querySelector('[data-testid="filter-input"]')).not.toBeNull();
    });
    expect(content.querySelector('[data-testid="filters-table"]')).not.toBeNull();
    expect(screen.getByTestId("settings-inline")).toBeInTheDocument();
    expect(screen.getByTestId("settings-audio-voice")).toBeInTheDocument();
    expect(screen.getByTestId("settings-perf-parallel")).toBeInTheDocument();
  });

  it("format radios set the wizard audio format", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("advanced-toggle"));
    const m4b = screen.getByTestId("wizard-format-m4b");
    expect(m4b).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByTestId("wizard-format-mp3"));
    expect(screen.getByTestId("wizard-format-mp3")).toHaveAttribute("aria-checked", "true");
    expect(m4b).toHaveAttribute("aria-checked", "false");
  });

  it("filters-updated event from advanced filters keeps the panel open (integration)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("advanced-toggle"));
    const content = await screen.findByTestId("advanced-content");
    await waitFor(() => {
      expect(content.querySelector('[data-testid="filter-input"]')).not.toBeNull();
    });
    const input = content.querySelector('[data-testid="filter-input"]') as HTMLInputElement;
    await user.type(input, "Subscribe");
    const addBtn = content.querySelector('[data-testid="filter-add"]') as HTMLButtonElement;
    await user.click(addBtn);
    const evt = new CustomEvent("filters-updated");
    window.dispatchEvent(evt);
    expect(screen.getByTestId("advanced-content")).toBeInTheDocument();
  });

  it("chapter list chunk hidden without a selected novel", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByTestId("advanced-toggle"));
    expect(await screen.findByTestId("advanced-content")).toBeInTheDocument();
    expect(screen.queryByTestId("advanced-chapters")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chapter-list-toggle")).not.toBeInTheDocument();
  });
});
