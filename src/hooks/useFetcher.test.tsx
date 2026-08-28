import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useFetcher } from "./useFetcher";

const mockCallSidecar = vi.fn();
const mockOnThrottleChanged = vi.fn();
const mockOnLogLine = vi.fn();
const mockOnChapterStatus = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  callSidecar: (...args: unknown[]) => mockCallSidecar(...args),
  onThrottleChanged: (cb: (p: unknown) => void) => {
    mockOnThrottleChanged(cb);
    return Promise.resolve(() => {});
  },
  onLogLine: (cb: (p: unknown) => void) => {
    mockOnLogLine(cb);
    return Promise.resolve(() => {});
  },
  onChapterStatus: (cb: (p: unknown) => void) => {
    mockOnChapterStatus(cb);
    return Promise.resolve(() => {});
  },
}));

describe("useFetcher hook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true } as unknown as { shouldAdvanceTime: boolean });
    // default resolve for listeners
    mockOnThrottleChanged.mockImplementation((_cb: unknown) => {
      void _cb;
      return Promise.resolve(() => {}) as unknown as Promise<() => void>;
    });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("initial state polite throttle badge", async () => {
    mockCallSidecar.mockResolvedValue({ id: "1", result: { chapters: [], skipped: 0, badge: null, logs: [] } });
    const { result } = renderHook(() => useFetcher());
    // after mount, throttle should be polite (default) or set via effect after 4000
    await waitFor(() => expect(result.current.throttle).toBeTruthy());
    expect(result.current.throttle?.tier).toBe("polite");
    expect(result.current.fetching).toBe(false);
    expect(result.current.logs).toEqual([]);
  });

  it("throttleChanged event updates badge to safe", async () => {
    let throttleCb: (p: { tier: string; delay: number }) => void = () => {};
    mockOnThrottleChanged.mockImplementation((cb) => {
      throttleCb = cb as unknown as (p: { tier: string; delay: number }) => void;
      return Promise.resolve(() => {}) as unknown as Promise<() => void>;
    });
    mockCallSidecar.mockResolvedValue({ id: "1", result: { chapters: [], skipped: 0 } });
    const { result } = renderHook(() => useFetcher());
    // wait for mount
    await waitFor(() => expect(mockOnThrottleChanged).toHaveBeenCalled());
    // simulate Core emit throttleChanged safe 10000
    act(() => {
      throttleCb({ tier: "safe", delay: 10000 });
    });
    await waitFor(() => expect(result.current.throttle?.tier).toBe("safe"));
    expect(result.current.throttle?.delay).toBe(10000);
    // log pane should contain throttle log
    expect(result.current.logs.some((l) => l.includes("safe"))).toBe(true);
  });

  it("bounded skip 21–100 pominięto badge", async () => {
    const urls = Array.from({ length: 100 }, (_, i) => `https://www.novelphoenix.com/novel/123/chapter/${i + 1}`);
    const mockChapters = Array.from({ length: 80 }, (_, i) => ({
      url: `https://www.novelphoenix.com/novel/123/chapter/${i + 21}`,
      title: `Chapter ${i + 21}`,
      html: `<div>${i + 21}</div>`,
      text: "text",
    }));
    mockCallSidecar.mockResolvedValue({
      id: "1",
      result: {
        chapters: mockChapters,
        skipped: 20,
        total: 100,
        badge: "pominięto 20, pobieram 21–100",
        logs: ["pominięto 20, pobieram 21–100", "skipped 20"],
        throttles: [],
      },
    });
    const { result } = renderHook(() => useFetcher());
    await act(async () => {
      await result.current.start({ urls, novelUrl: "https://www.novelphoenix.com/novel/123", from: 1, to: 100 });
    });
    await waitFor(() => expect(result.current.fetching).toBe(false));
    expect(result.current.badge).toBe("pominięto 20, pobieram 21–100");
    expect(result.current.logs.some((l) => l.includes("pominięto 20"))).toBe(true);
    // callSidecar should have been called with correct params
    expect(mockCallSidecar).toHaveBeenCalledWith("fetchChapters", expect.objectContaining({ urls, novelUrl: "https://www.novelphoenix.com/novel/123", from: 1, to: 100 }), expect.anything());
  });

  it("open-ended wykryto 42 nowe", async () => {
    mockCallSidecar.mockResolvedValue({
      id: "1",
      result: {
        chapters: Array.from({ length: 42 }, (_, i) => ({
          url: `https://www.novelphoenix.com/novel/123/chapter/${i + 101}`,
          title: `Chapter ${i + 101}`,
          html: "<div>html</div>",
          text: "text",
        })),
        skipped: 100,
        total: 142,
        badge: "pominięto 100, wykryto 42 nowe",
        logs: ["pominięto 100, wykryto 42 nowe"],
        throttles: [],
      },
    });
    const { result } = renderHook(() => useFetcher());
    await act(async () => {
      await result.current.start({ urls: [], novelUrl: "https://www.novelphoenix.com/novel/123", from: 1, to: null });
    });
    await waitFor(() => expect(result.current.badge).toBe("pominięto 100, wykryto 42 nowe"));
    expect(result.current.logs.some((l) => l.includes("wykryto 42 nowe"))).toBe(true);
    expect(mockCallSidecar).toHaveBeenCalledWith("fetchChapters", expect.objectContaining({ novelUrl: "https://www.novelphoenix.com/novel/123", to: null }), expect.anything());
  });

  it("LIST_FAILED mapping sets error and log", async () => {
    mockCallSidecar.mockResolvedValue({ id: "1", error: { code: "LIST_FAILED", message: "404" } });
    const { result } = renderHook(() => useFetcher());
    await act(async () => {
      await result.current.start({ urls: ["https://www.novelphoenix.com/novel/123/chapter/1"] });
    });
    await waitFor(() => expect(result.current.error).toBe("LIST_FAILED"));
    expect(result.current.logs.some((l) => l.includes("LIST_FAILED"))).toBe(true);
    expect(result.current.fetching).toBe(false);
  });

  it("handles logLine event badge pominięto via event bus", async () => {
    let logCb: (p: { line: string }) => void = () => {};
    mockOnLogLine.mockImplementation((cb) => {
      logCb = cb as unknown as (p: { line: string }) => void;
      return Promise.resolve(() => {}) as unknown as Promise<() => void>;
    });
    mockCallSidecar.mockResolvedValue({ id: "1", result: { chapters: [], skipped: 0 } });
    const { result } = renderHook(() => useFetcher());
    await waitFor(() => expect(mockOnLogLine).toHaveBeenCalled());
    act(() => {
      logCb({ line: "pominięto 5, wykryto 3 nowe" });
    });
    await waitFor(() => expect(result.current.badge).toBe("pominięto 5, wykryto 3 nowe"));
    expect(result.current.logs).toContain("pominięto 5, wykryto 3 nowe");
  });

  it("chapterStatus events update statuses", async () => {
    let statusCb: (p: { chapter: number; status: string }) => void = () => {};
    mockOnChapterStatus.mockImplementation((cb) => {
      statusCb = cb as unknown as (p: { chapter: number; status: string }) => void;
      return Promise.resolve(() => {}) as unknown as Promise<() => void>;
    });
    mockCallSidecar.mockImplementation(() => new Promise(() => {})); // never resolves to keep fetching
    const { result } = renderHook(() => useFetcher());
    await waitFor(() => expect(mockOnChapterStatus).toHaveBeenCalled());
    // Start fetch to set statuses queued
    const urls = ["https://www.novelphoenix.com/novel/123/chapter/1", "https://www.novelphoenix.com/novel/123/chapter/2"];
    // start without awaiting (still fetching)
    act(() => {
      // don't await, just trigger
      void result.current.start({ urls });
    });
    await waitFor(() => expect(result.current.fetching).toBe(true));
    // simulate chapterStatus events
    act(() => {
      statusCb({ chapter: 1, status: "fetching" });
      statusCb({ chapter: 2, status: "queued" });
    });
    await waitFor(() => expect(result.current.statuses[1]).toBe("fetching"));
    expect(result.current.statuses[2]).toBe("queued");
    act(() => {
      statusCb({ chapter: 1, status: "done" });
    });
    await waitFor(() => expect(result.current.statuses[1]).toBe("done"));
  });
});
