import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Audiobook, { formatDuration } from "./Audiobook";

const mockBuildAudio = vi.fn();
const mockGetStore = vi.fn();
const mockInvoke = vi.fn();
const mockOnMergeProgress = vi.fn();

vi.mock("@/lib/sidecar", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    buildAudio: (...args: unknown[]) => mockBuildAudio(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args),
    onMergeProgress: (...args: unknown[]) => mockOnMergeProgress(...args),
  };
});

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

const baseProps = {
  novelUrl: "https://www.novelphoenix.com/novel/123",
  from: 1,
  to: 1,
  title: "Test Book",
  urls: ["https://www.novelphoenix.com/novel/123/chapter/1"],
  canStart: true,
  fetching: false,
  progress: { done: 0, total: 0, percent: 0 },
  onClearParts: vi.fn(),
};

describe("Audiobook — Step 7 MP3/M4B/M4A", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetStore.mockResolvedValue({
      id: "1",
      result: { voice: "en-US-AndrewNeural", parallel: 3, "chunk-size": 3500, retries: 5 },
    });
    mockInvoke.mockResolvedValue(undefined);
  });

  it("renders empty state with format radio default m4b", async () => {
    render(<Audiobook {...baseProps} />);
    expect(screen.getByTestId("audiobook-section")).toBeInTheDocument();
    expect(screen.getByTestId("audio-empty")).toBeInTheDocument();
    expect(screen.getByTestId("audio-format-m4b")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("audio-format-mp3")).toHaveAttribute("aria-checked", "false");
    await waitFor(() => {
      expect(screen.getByText(/en-US-AndrewNeural/)).toBeInTheDocument();
    });
  });

  it("format radio switches mp3/m4b/m4a", async () => {
    const user = userEvent.setup();
    render(<Audiobook {...baseProps} />);
    await user.click(screen.getByTestId("audio-format-mp3"));
    expect(screen.getByTestId("audio-format-mp3")).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByTestId("audio-format-m4a"));
    expect(screen.getByTestId("audio-format-m4a")).toHaveAttribute("aria-checked", "true");
  });

  it("build disabled without urls or while fetching", () => {
    render(<Audiobook {...baseProps} urls={[]} />);
    expect(screen.getByTestId("audio-build")).toBeDisabled();
    render(<Audiobook {...baseProps} fetching={true} />);
    // second render's button also disabled (fetching blocks shared bus)
    const btns = screen.getAllByTestId("audio-build");
    expect(btns[1]).toBeDisabled();
  });

  it("successful m4b build shows result card with path and open", async () => {
    const user = userEvent.setup();
    mockBuildAudio.mockResolvedValue({
      id: "1",
      result: {
        audio_dir: "output/Test_Book_audiobook",
        chapter_count: 1,
        part_count: 2,
        chapters: [{ number: 1, title: "Chapter 1", path: "output/Test_Book_audiobook/001_Chapter_1.mp3" }],
        audiobook: { path: "output/Test_Book_audiobook/Test_Book_chapters_001_to_001.m4b", size: 123456, format: "m4b" },
        format: "m4b",
        voice: "en-US-AndrewNeural",
        ffmpeg: true,
      },
    });
    const onClearParts = vi.fn();
    render(<Audiobook {...baseProps} onClearParts={onClearParts} />);
    await user.click(screen.getByTestId("audio-build"));
    expect(onClearParts).toHaveBeenCalledTimes(1);
    expect(mockBuildAudio).toHaveBeenCalledWith(
      expect.objectContaining({
        novelUrl: baseProps.novelUrl,
        urls: baseProps.urls,
        format: "m4b",
      })
    );
    await waitFor(() => {
      expect(screen.getByTestId("audio-result")).toBeInTheDocument();
    });
    expect(screen.getByTestId("audio-path").textContent).toContain(".m4b");
    expect(screen.getByTestId("audio-open")).toBeInTheDocument();
    await user.click(screen.getByTestId("audio-open"));
    expect(mockInvoke).toHaveBeenCalled();
  });
  it("CACHE_MISS shows fetch-first hint with missing", async () => {
    const user = userEvent.setup();
    mockBuildAudio.mockResolvedValue({
      id: "1",
      error: { code: "CACHE_MISS", message: "cache miss 1", missing: ["https://x/chapter/9"] },
    });
    render(<Audiobook {...baseProps} />);
    await user.click(screen.getByTestId("audio-build"));
    await waitFor(() => {
      expect(screen.getByTestId("audio-error")).toBeInTheDocument();
    });
    const err = screen.getByTestId("audio-error").textContent ?? "";
    expect(err).toMatch(/Fetch chapters first|Najpierw pobierz/i);
    expect(err).toContain("https://x/chapter/9");
  });

  it("m4b without ffmpeg shows missing-ffmpeg warning, no file button", async () => {
    const user = userEvent.setup();
    mockBuildAudio.mockResolvedValue({
      id: "1",
      result: {
        audio_dir: "output/Book_audiobook",
        chapter_count: 1,
        part_count: 2,
        chapters: [{ number: 1, title: "Chapter 1", path: "output/Book_audiobook/_parts/001_C_part001.mp3" }],
        audiobook: null,
        format: "m4b",
        voice: "en-US-AndrewNeural",
        ffmpeg: false,
      },
    });
    render(<Audiobook {...baseProps} />);
    await user.click(screen.getByTestId("audio-build"));
    await waitFor(() => {
      expect(screen.getByTestId("audio-ffmpeg-warning")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("audio-open")).not.toBeInTheDocument();
    expect(screen.getByTestId("audio-open-folder")).toBeInTheDocument();
  });

  it("m4b with ffmpeg and no audiobook shows no ffmpeg warning", async () => {
    const user = userEvent.setup();
    mockBuildAudio.mockResolvedValue({
      id: "1",
      result: {
        audio_dir: "output/Book_audiobook",
        chapter_count: 1,
        part_count: 2,
        chapters: [],
        audiobook: null,
        format: "m4b",
        voice: "en-US-AndrewNeural",
        ffmpeg: true,
      },
    });
    render(<Audiobook {...baseProps} />);
    await user.click(screen.getByTestId("audio-build"));
    await waitFor(() => {
      expect(screen.getByTestId("audio-result")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("audio-ffmpeg-warning")).not.toBeInTheDocument();
  });

  it("mp3 result shows open folder button", async () => {
    const user = userEvent.setup();
    mockBuildAudio.mockResolvedValue({
      id: "1",
      result: {
        audio_dir: "output/Book_audiobook",
        chapter_count: 2,
        part_count: 2,
        chapters: [
          { number: 1, title: "Chapter 1", path: "output/Book_audiobook/001_C1.mp3" },
          { number: 2, title: "Chapter 2", path: "output/Book_audiobook/002_C2.mp3" },
        ],
        audiobook: null,
        format: "mp3",
        voice: "en-US-AndrewNeural",
        ffmpeg: true,
      },
    });
    render(<Audiobook {...baseProps} />);
    await user.click(screen.getByTestId("audio-format-mp3"));
    await user.click(screen.getByTestId("audio-build"));
    await waitFor(() => {
      expect(screen.getByTestId("audio-open-folder")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("audio-open")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("audio-open-folder"));
    expect(mockInvoke).toHaveBeenCalledWith(
      expect.stringContaining("reveal_item_in_dir"),
      expect.objectContaining({ paths: ["output/Book_audiobook"] })
    );
  });

  it("formatDuration helper", () => {
    expect(formatDuration(7)).toBe("7s");
    expect(formatDuration(65)).toBe("1m 05s");
    expect(formatDuration(260)).toBe("4m 20s");
  });

  it("shows elapsed + ETA while building", async () => {
    vi.useFakeTimers();
    try {
      mockBuildAudio.mockReturnValue(new Promise(() => {}));
      render(<Audiobook {...baseProps} progress={{ done: 2, total: 10, percent: 20 }} />);
      fireEvent.click(screen.getByTestId("audio-build"));
      expect(screen.getByTestId("audio-building")).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(65000);
      const eta = screen.getByTestId("audio-eta").textContent ?? "";
      // 65s elapsed, 2/10 parts → ≈260s left
      expect(eta).toMatch(/elapsed|minęło/);
      expect(eta).toMatch(/left|pozostało/);
      expect(eta).toContain("4m 20s");
    } finally {
      vi.useRealTimers();
    }
  }, 30000);

  it("merge phase shows chapter progress with its own ETA", async () => {
    vi.useFakeTimers();
    try {
      mockBuildAudio.mockReturnValue(new Promise(() => {}));
      mockOnMergeProgress.mockImplementation((cb: unknown) => {
        (globalThis as Record<string, unknown>).__mergeCb = cb;
        return Promise.resolve(() => {});
      });
      render(<Audiobook {...baseProps} progress={{ done: 9, total: 9, percent: 100 }} />);
      fireEvent.click(screen.getByTestId("audio-build"));
      expect(screen.getByTestId("audio-building")).toBeInTheDocument();
      const cb = (globalThis as Record<string, unknown>).__mergeCb as (p: unknown) => void;
      const { act } = await import("@testing-library/react");
      await act(async () => {
        cb({ phase: "merging", done: 3, total: 10 });
      });
      await vi.advanceTimersByTimeAsync(31000);
      const eta = screen.getByTestId("audio-eta").textContent ?? "";
      // merge clock: 31s for 3/10 chapters → ≈72s left
      expect(eta).toMatch(/Merging chapters 3\/10|Scalanie rozdziałów 3\/10/);
      expect(eta).toContain("1m 12s");
    } finally {
      vi.useRealTimers();
      delete (globalThis as Record<string, unknown>).__mergeCb;
    }
  }, 30000);

  it("multiplex phase shows indeterminate building text", async () => {
    vi.useFakeTimers();
    try {
      mockBuildAudio.mockReturnValue(new Promise(() => {}));
      mockOnMergeProgress.mockImplementation((cb: unknown) => {
        (globalThis as Record<string, unknown>).__mergeCb = cb;
        return Promise.resolve(() => {});
      });
      render(<Audiobook {...baseProps} progress={{ done: 9, total: 9, percent: 100 }} />);
      fireEvent.click(screen.getByTestId("audio-build"));
      const cb = (globalThis as Record<string, unknown>).__mergeCb as (p: unknown) => void;
      const { act } = await import("@testing-library/react");
      await act(async () => {
        cb({ phase: "multiplex", done: 0, total: 1 });
      });
      await vi.advanceTimersByTimeAsync(5000);
      const eta = screen.getByTestId("audio-eta").textContent ?? "";
      expect(eta).toMatch(/Building M4B|Budowanie pliku M4B/);
    } finally {
      vi.useRealTimers();
      delete (globalThis as Record<string, unknown>).__mergeCb;
    }
  }, 30000);

  it("multiplex phase shows byte-scale percent + remaining", async () => {
    vi.useFakeTimers();
    try {
      mockBuildAudio.mockReturnValue(new Promise(() => {}));
      mockOnMergeProgress.mockImplementation((cb: unknown) => {
        (globalThis as Record<string, unknown>).__mergeCb = cb;
        return Promise.resolve(() => {});
      });
      render(<Audiobook {...baseProps} progress={{ done: 9, total: 9, percent: 100 }} />);
      fireEvent.click(screen.getByTestId("audio-build"));
      const cb = (globalThis as Record<string, unknown>).__mergeCb as (p: unknown) => void;
      const { act } = await import("@testing-library/react");
      await act(async () => {
        cb({ phase: "multiplex", done: 1048576, total: 2097152 });
      });
      await vi.advanceTimersByTimeAsync(31000);
      const eta = screen.getByTestId("audio-eta").textContent ?? "";
      // 31s elapsed at 50% → ≈31s left
      expect(eta).toMatch(/50%/);
      expect(eta).toMatch(/left|pozostało/);
      expect(eta).toContain("31s");
    } finally {
      vi.useRealTimers();
      delete (globalThis as Record<string, unknown>).__mergeCb;
    }
  }, 30000);

  it("probing phase shows file counts with ETA", async () => {
    vi.useFakeTimers();
    try {
      mockBuildAudio.mockReturnValue(new Promise(() => {}));
      mockOnMergeProgress.mockImplementation((cb: unknown) => {
        (globalThis as Record<string, unknown>).__mergeCb = cb;
        return Promise.resolve(() => {});
      });
      render(<Audiobook {...baseProps} progress={{ done: 9, total: 9, percent: 100 }} />);
      fireEvent.click(screen.getByTestId("audio-build"));
      const cb = (globalThis as Record<string, unknown>).__mergeCb as (p: unknown) => void;
      const { act } = await import("@testing-library/react");
      await act(async () => {
        cb({ phase: "probing", done: 150, total: 300 });
      });
      await vi.advanceTimersByTimeAsync(21000);
      const eta = screen.getByTestId("audio-eta").textContent ?? "";
      // 21s elapsed at 150/300 → ≈21s left
      expect(eta).toMatch(/Probing audio files 150\/300|Sprawdzanie plików audio 150\/300/);
      expect(eta).toMatch(/left|pozostało/);
      expect(eta).toContain("21s");
    } finally {
      vi.useRealTimers();
      delete (globalThis as Record<string, unknown>).__mergeCb;
    }
  }, 30000);
});
