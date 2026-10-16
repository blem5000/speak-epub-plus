import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockCallSidecar = vi.fn();
const mockGetStore = vi.fn();
const mockSetStore = vi.fn();
const mockBuildEpub = vi.fn();
const mockBuildAudio = vi.fn();
const mockCancelSidecarJob = vi.fn();
const mockDialogOpen = vi.fn();

// Ordered timeline of wizard side effects (fetch → epub → audio)
let timeline: string[] = [];

vi.mock("@/lib/sidecar", async () => {
  const actual = await vi.importActual<typeof import("@/lib/sidecar")>("@/lib/sidecar");
  return {
    ...actual,
    callSidecar: (...args: unknown[]) => mockCallSidecar(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args),
    setStore: (...args: unknown[]) => mockSetStore(...args),
    buildEpub: (...args: unknown[]) => mockBuildEpub(...args),
    isEpubResult: (res: { result?: unknown }) => {
      if (!res.result || typeof res.result !== "object") return false;
      const r = res.result as Record<string, unknown>;
      return typeof r.path === "string";
    },
    buildAudio: (...args: unknown[]) => mockBuildAudio(...args),
    isAudioResult: (res: { result?: unknown }) => {
      if (!res.result || typeof res.result !== "object") return false;
      const r = res.result as Record<string, unknown>;
      const ab = r.audiobook as Record<string, unknown> | undefined;
      return typeof ab?.path === "string" || typeof r.audioDir === "string";
    },
    cancelSidecarJob: (...args: unknown[]) => mockCancelSidecarJob(...args),
    onMergeProgress: () => Promise.resolve(() => {}),
    onThrottleChanged: () => Promise.resolve(() => {}),
    onLogLine: () => Promise.resolve(() => {}),
    onChapterStatus: () => Promise.resolve(() => {}),
    onPartStatus: () => Promise.resolve(() => {}),
  };
});

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => mockDialogOpen(...args),
}));

// Results must contain the selected URL — otherwise App's stale-selection
// guard (results no longer contain selectedUrl → clear it) wipes it on mount.
let resultsMock: unknown[] = [];

vi.mock("@/hooks/useDebouncedSearch", () => ({
  useDebouncedSearch: () => ({ searching: false, results: resultsMock, error: null }),
}));
vi.mock("@/hooks/useChapterList", () => ({
  useChapterList: () => ({
    loading: false,
    list: [
      { index: 1, title: "Chapter 1", url: "https://www.novelphoenix.com/novel/123/chapter/1" },
      { index: 2, title: "Chapter 2", url: "https://www.novelphoenix.com/novel/123/chapter/2" },
    ],
    error: null,
    cover: null,
  }),
}));

import App from "./App";

const AUDIO_RESULT = {
  id: "1",
  result: { audiobook: { path: "D:\\Books\\out\\book.m4b", size: 1024, format: "m4b" }, chapters: 2, parts: 2 },
};
const EPUB_RESULT = {
  id: "1",
  result: { path: "D:\\Books\\out\\book.epub", size: 123, chapter_count: 2, epubcheck_ok: true, messages: [] },
};

describe("App wizard — single Start orchestration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    timeline = [];
    resultsMock = [
      {
        url: "https://www.novelphoenix.com/novel/123",
        site: "novelphoenix.com",
        title: "Test Book",
        chapters: 2,
        author: "Author",
      },
    ];
    mockCallSidecar.mockImplementation(async (method: unknown) => {
      if (method === "hello") return { id: "0", result: { pong: true } };
      if (method === "getSelection")
        return { id: "0", result: { selection: [], from: 1, to: 2, url: "https://www.novelphoenix.com/novel/123" } };
      if (method === "fetchChapters") {
        timeline.push("fetch");
        return { id: "0", result: { chapters: [], skipped: 0, total: 2 } };
      }
      return { id: "0", result: {} };
    });
    mockGetStore.mockResolvedValue({ id: "0", result: { voice: "en-US-AndrewNeural", parallel: 2, locale: "en" } });
    mockSetStore.mockResolvedValue({ id: "0", result: {} });
    mockBuildEpub.mockImplementation(async () => {
      timeline.push("epub");
      return EPUB_RESULT;
    });
    mockBuildAudio.mockImplementation(async () => {
      timeline.push("audio");
      return AUDIO_RESULT;
    });
    mockCancelSidecarJob.mockResolvedValue(0);
    mockDialogOpen.mockResolvedValue("D:\\Books\\Audio");
  });

  it("renders wizard options once a novel is selected", async () => {
    render(<App />);
    const options = await screen.findByTestId("wizard-options");
    expect(options).toBeInTheDocument();
    expect(screen.getByTestId("range-from")).toBeInTheDocument();
    expect(screen.getByTestId("range-to")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-want-epub")).toBeChecked();
    expect(screen.getByTestId("wizard-want-audio")).toBeChecked();
    expect(screen.getByTestId("wizard-output-dir")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-pick-folder")).toBeInTheDocument();
    expect(screen.queryByTestId("wizard-no-targets")).not.toBeInTheDocument();
  });

  it("single Start runs fetch → epub → audio in order and renders both results", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("wizard-options");
    await user.click(screen.getByTestId("range-start"));
    await waitFor(() => expect(mockBuildAudio).toHaveBeenCalledTimes(1));
    expect(timeline).toEqual(["fetch", "epub", "audio"]);
    // buildAudio received the wizard format and target range
    const audioParams = mockBuildAudio.mock.calls[0][0] as Record<string, unknown>;
    expect(audioParams.format).toBe("m4b");
    expect(audioParams.from).toBe(1);
    expect(audioParams.to).toBe(2);
    expect(audioParams.urls).toEqual([
      "https://www.novelphoenix.com/novel/123/chapter/1",
      "https://www.novelphoenix.com/novel/123/chapter/2",
    ]);
    // both result sections appear (gated by *_touched)
    expect(await screen.findByTestId("result-section")).toBeInTheDocument();
    expect(await screen.findByTestId("audiobook-section")).toBeInTheDocument();
    expect(await screen.findByTestId("audio-result")).toBeInTheDocument();
  });

  it("audio-only run skips EPUB when the checkbox is unchecked", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("wizard-options");
    await user.click(screen.getByTestId("wizard-want-epub"));
    expect(screen.getByTestId("wizard-want-epub")).not.toBeChecked();
    await user.click(screen.getByTestId("range-start"));
    await waitFor(() => expect(mockBuildAudio).toHaveBeenCalledTimes(1));
    expect(mockBuildEpub).not.toHaveBeenCalled();
    expect(timeline).toEqual(["fetch", "audio"]);
    // Result section gated off (never touched)
    expect(screen.queryByTestId("result-section")).not.toBeInTheDocument();
  });

  it("no-op Start with both targets unchecked shows the hint", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("wizard-options");
    await user.click(screen.getByTestId("wizard-want-epub"));
    await user.click(screen.getByTestId("wizard-want-audio"));
    expect(screen.getByTestId("wizard-no-targets")).toBeInTheDocument();
    await user.click(screen.getByTestId("range-start"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(timeline).toEqual([]);
    expect(mockBuildEpub).not.toHaveBeenCalled();
    expect(mockBuildAudio).not.toHaveBeenCalled();
  });

  it("Stop button aborts a running wizard job", async () => {
    const user = userEvent.setup();
    // fetchChapters never resolves → job stuck in fetching phase
    mockCallSidecar.mockImplementation(async (method: unknown) => {
      if (method === "getSelection")
        return { id: "0", result: { selection: [], from: 1, to: 2, url: "https://www.novelphoenix.com/novel/123" } };
      if (method === "fetchChapters") return await new Promise(() => {});
      return { id: "0", result: {} };
    });
    render(<App />);
    await screen.findByTestId("wizard-options");
    await user.click(screen.getByTestId("range-start"));
    const stop = await screen.findByTestId("wizard-stop");
    expect(stop).toBeInTheDocument();
    await user.click(stop);
    await waitFor(() => expect(screen.queryByTestId("wizard-stop")).not.toBeInTheDocument());
    expect(mockCancelSidecarJob).toHaveBeenCalled();
  });

  it("folder picker persists outputDir and shows it", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId("wizard-options");
    await user.click(screen.getByTestId("wizard-pick-folder"));
    await waitFor(() => {
      expect(mockSetStore).toHaveBeenCalledWith({ outputDir: "D:\\Books\\Audio" });
    });
    expect(screen.getByTestId("wizard-output-dir").textContent).toContain("D:\\Books\\Audio");
  });
});
