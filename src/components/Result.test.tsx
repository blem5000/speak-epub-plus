import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Result from "./Result";

const mockGetStore = vi.fn();
const mockSetStore = vi.fn();
const mockInvoke = vi.fn();

vi.mock("@/lib/sidecar", async (importOriginal) => {
  const actual = await importOriginal() as Record<string, unknown>;
  return {
    ...actual,
    getStore: (...args: unknown[]) => mockGetStore(...args),
    setStore: (...args: unknown[]) => mockSetStore(...args),
  };
});

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

describe("Result 2.4 — EPUB assembly + epubcheck", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetStore.mockResolvedValue({ id: "1", result: { keepEPUB: true, filters: [] } });
    mockSetStore.mockResolvedValue({ id: "1", result: { keepEPUB: false } });
    mockInvoke.mockResolvedValue(undefined);
  });

  it("renders empty state Nie zbudowano when not built", async () => {
    render(<Result result={null} building={false} error={null} canBuild={false} onBuild={vi.fn()} />);
    expect(screen.getByTestId("result-section")).toBeInTheDocument();
    expect(screen.getByTestId("result-empty")).toBeInTheDocument();
    expect(screen.getByTestId("result-empty").textContent).toMatch(/Nie zbudowano|Not built/);
    expect(screen.getByTestId("epubcheck-badge")).toBeInTheDocument();
  });

  it("shows path mono size and epubcheck badge ✓ clean", async () => {
    const result = {
      path: "output/Lord_chapters_001_to_020.epub",
      size: 12345,
      chapter_count: 20,
      epubcheck_ok: true,
      messages: ["proxy clean"],
      logs: [],
    } as unknown as import("@/lib/sidecar").EpubResult;
    render(<Result result={result} building={false} error={null} canBuild={true} onBuild={vi.fn()} from={1} to={20} />);
    expect(screen.getByTestId("result-path")).toBeInTheDocument();
    expect(screen.getByTestId("result-path").textContent).toContain("Lord_chapters_001_to_020.epub");
    expect(screen.getByTestId("result-path").className).toContain("mono");
    expect(screen.getByTestId("result-size")).toBeInTheDocument();
    expect(screen.getByTestId("result-size").textContent).toMatch(/KB|MB|B/);
    expect(screen.getByTestId("epubcheck-badge")).toBeInTheDocument();
    expect(screen.getByTestId("epubcheck-badge").textContent).toMatch(/✓|clean|proxy/i);
    expect(screen.getByTestId("open-folder")).toBeInTheDocument();
  });

  it("shows epubcheck proxy ~ when proxy", async () => {
    const result = {
      path: "output/Test_chapters_001_to_001.epub",
      size: 5000,
      chapter_count: 1,
      epubcheck_ok: true,
      messages: ["epubcheck not found — using ebooklib proxy", "proxy clean"],
      logs: [],
    } as unknown as import("@/lib/sidecar").EpubResult;
    render(<Result result={result} building={false} error={null} canBuild={true} onBuild={vi.fn()} />);
    expect(screen.getByTestId("epubcheck-badge").textContent).toMatch(/~|proxy/i);
  });

  it("shows epubcheck ✗ fail when dirty", async () => {
    const result = {
      path: "output/Test_chapters_001_to_001.epub",
      size: 5000,
      chapter_count: 1,
      epubcheck_ok: false,
      messages: ["error: malformed XHTML"],
      logs: [],
    } as unknown as import("@/lib/sidecar").EpubResult;
    render(<Result result={result} building={false} error={null} canBuild={true} onBuild={vi.fn()} />);
    expect(screen.getByTestId("epubcheck-badge").textContent).toMatch(/✗|fail/i);
  });

  it("open folder invokes Tauri opener", async () => {
    const result = {
      path: "output/Test_chapters_001_to_001.epub",
      size: 5000,
      chapter_count: 1,
      epubcheck_ok: true,
      messages: [],
      logs: [],
    } as unknown as import("@/lib/sidecar").EpubResult;
    const user = userEvent.setup();
    render(<Result result={result} building={false} error={null} canBuild={true} onBuild={vi.fn()} />);
    await user.click(screen.getByTestId("open-folder"));
    await waitFor(() => expect(mockInvoke).toHaveBeenCalled());
    expect(mockInvoke).toHaveBeenCalledWith(expect.stringContaining("opener"), expect.objectContaining({ path: result.path }));
  });

  it("keepEPUB switch reflects store and toggles", async () => {
    const user = userEvent.setup();
    render(<Result result={null} building={false} error={null} canBuild={false} onBuild={vi.fn()} />);
    // wait for getStore to be called and switch to reflect true
    await waitFor(() => expect(mockGetStore).toHaveBeenCalled());
    const toggle = screen.getByTestId("keep-epub") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    await user.click(toggle);
    await waitFor(() => expect(mockSetStore).toHaveBeenCalledWith({ keepEPUB: false }));
  });

  it("shows cacheMiss error and badge", async () => {
    render(<Result result={null} building={false} error={"CACHE_MISS: cache miss 1"} missing={["https://www.novelphoenix.com/novel/123/chapter/7"]} canBuild={true} onBuild={vi.fn()} />);
    expect(screen.getByTestId("cache-miss")).toBeInTheDocument();
    expect(screen.getByTestId("cache-miss").textContent).toMatch(/cache miss/i);
    expect(screen.getByTestId("result-error")).toBeInTheDocument();
  });

  it("building state shows building text and disables", async () => {
    render(<Result result={null} building={true} error={null} canBuild={false} onBuild={vi.fn()} />);
    expect(screen.getByTestId("result-building")).toBeInTheDocument();
    expect(screen.getByTestId("result-building").textContent).toMatch(/Budowanie|Building/i);
  });

  it("shows chapters count and size humanized", async () => {
    const result = {
      path: "output/Test_chapters_005_to_007.epub",
      size: 2048,
      chapter_count: 3,
      epubcheck_ok: true,
      messages: [],
      logs: [],
    } as unknown as import("@/lib/sidecar").EpubResult;
    render(<Result result={result} building={false} error={null} canBuild={true} onBuild={vi.fn()} from={5} to={7} />);
    expect(screen.getByTestId("result-chapters").textContent).toMatch(/3/);
    expect(screen.getByTestId("result-size").textContent).toMatch(/2\.0 KB|2048/);
  });
});
