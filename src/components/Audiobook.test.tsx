import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Audiobook from "./Audiobook";

const mockBuildAudio = vi.fn();
const mockGetStore = vi.fn();
const mockInvoke = vi.fn();

vi.mock("@/lib/sidecar", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    buildAudio: (...args: unknown[]) => mockBuildAudio(...args),
    getStore: (...args: unknown[]) => mockGetStore(...args),
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
});
