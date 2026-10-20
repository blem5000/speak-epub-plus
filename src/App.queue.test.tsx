import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockCallSidecar = vi.fn();

vi.mock("@/lib/sidecar", async () => {
  const actual = await vi.importActual<typeof import("@/lib/sidecar")>("@/lib/sidecar");
  return {
    ...actual,
    callSidecar: (...args: unknown[]) => mockCallSidecar(...args),
    getStore: vi.fn().mockResolvedValue({ id: "1", result: {} }),
    buildEpub: vi.fn().mockResolvedValue({ id: "1", result: { path: "x.epub", size: 1 } }),
  };
});

const results = [
  {
    site: "novelphoenix",
    title: "Pierwsza książka",
    url: "https://www.novelphoenix.com/a",
    link: "https://www.novelphoenix.com/a",
    chapters: 3,
  },
  {
    site: "novelphoenix",
    title: "Druga książka",
    url: "https://www.novelphoenix.com/b",
    link: "https://www.novelphoenix.com/b",
    chapters: 2,
  },
];

vi.mock("@/hooks/useDebouncedSearch", () => ({
  useDebouncedSearch: () => ({ searching: false, results, error: null }),
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

describe("App — batch queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // the App asks for the saved selection on mount
    mockCallSidecar.mockResolvedValue({ id: "1", result: {} });
  });

  it("adds a novel from the results table to the queue", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId("queue-add-0")).toBeInTheDocument());
    await user.click(screen.getByTestId("queue-add-0"));
    await waitFor(() => expect(screen.getByTestId("queue-panel")).toBeInTheDocument());
    expect(screen.getByTestId("queue-item-https://www.novelphoenix.com/a")).toBeInTheDocument();
  });

  it("converts the queued novels one after another", async () => {
    const user = userEvent.setup();
    mockCallSidecar.mockImplementation(async (method: string) => {
      if (method === "listChapters") {
        return {
          id: "1",
          result: {
            chapters: [
              { index: 1, title: "Rozdział 1", url: "https://x.test/c1" },
              { index: 2, title: "Rozdział 2", url: "https://x.test/c2" },
            ],
            cover_url: "https://x.test/cover.jpg",
          },
        };
      }
      if (method === "fetchChapters") return { id: "1", result: { ok: true } };
      if (method === "buildAudio") {
        return {
          id: "1",
          result: {
            audio_dir: "out/dir",
            chapter_count: 2,
            part_count: 2,
            chapters: [],
            format: "m4b",
            audiobook: { path: "out/book.m4b", size: 10, format: "m4b" },
          },
        };
      }
      return { id: "1", result: {} };
    });

    render(<App />);
    await waitFor(() => expect(screen.getByTestId("queue-add-0")).toBeInTheDocument());
    await user.click(screen.getByTestId("queue-add-0"));
    await waitFor(() => expect(screen.getByTestId("queue-panel")).toBeInTheDocument());
    await user.click(screen.getByTestId("queue-convert"));

    await waitFor(() => {
      const methods = mockCallSidecar.mock.calls.map((c) => c[0]);
      expect(methods).toContain("listChapters");
      expect(methods).toContain("fetchChapters");
      expect(methods).toContain("buildAudio");
    });
    const buildCall = mockCallSidecar.mock.calls.find((c) => c[0] === "buildAudio");
    expect(buildCall?.[1]).toMatchObject({
      novelUrl: "https://www.novelphoenix.com/a",
      from: 1,
      to: 2,
      coverUrl: "https://x.test/cover.jpg",
    });
    await waitFor(() =>
      expect(screen.getByTestId("queue-status-https://www.novelphoenix.com/a").textContent).toMatch(
        /Gotowe|Done/
      )
    );
  });

  it("records a failing book and continues with the next one", async () => {
    const user = userEvent.setup();
    let listCalls = 0;
    mockCallSidecar.mockImplementation(async (method: string) => {
      if (method === "listChapters") {
        listCalls += 1;
        if (listCalls === 1) throw new Error("list failed");
        return { id: "1", result: { chapters: [{ index: 1, title: "Rozdział 1", url: "https://x.test/c1" }] } };
      }
      if (method === "fetchChapters") return { id: "1", result: { ok: true } };
      if (method === "buildAudio") return { id: "1", result: { audio_dir: "out", chapter_count: 1, part_count: 1, chapters: [], format: "m4b", audiobook: null } };
      return { id: "1", result: {} };
    });

    render(<App />);
    await waitFor(() => expect(screen.getByTestId("queue-add-0")).toBeInTheDocument());
    await user.click(screen.getByTestId("queue-add-0"));
    await waitFor(() => expect(screen.getByTestId("queue-panel")).toBeInTheDocument());
    await user.click(screen.getByTestId("queue-convert"));

    await waitFor(() =>
      expect(screen.getByTestId("queue-status-https://www.novelphoenix.com/a").textContent).toContain(
        "list failed"
      )
    );
  });
});
