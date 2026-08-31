import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Preview from "./Preview";

const mockPreviewChapter = vi.fn();
const mockGetSelectors = vi.fn();
const mockSaveSelectors = vi.fn();
const mockClearSelectors = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  previewChapter: (...args: unknown[]) => mockPreviewChapter(...args),
  getSelectors: (...args: unknown[]) => mockGetSelectors(...args),
  saveSelectors: (...args: unknown[]) => mockSaveSelectors(...args),
  clearSelectors: (...args: unknown[]) => mockClearSelectors(...args),
  isPreviewResult: (res: { result?: unknown }) => {
    if (!res.result || typeof res.result !== "object") return false;
    const r = res.result as Record<string, unknown>;
    return typeof r.html === "string" && typeof r.text === "string";
  },
}));

describe("Preview 2.2 — selector boundary + live re-parse", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true } as unknown as { shouldAdvanceTime: boolean });
    mockGetSelectors.mockResolvedValue({
      id: "1",
      result: { site: "novelphoenix.com", start: "div#chapter-content", end: null, defaultStart: "div#chapter-content", defaultEnd: null, override: null },
    });
    mockPreviewChapter.mockResolvedValue({
      id: "1",
      result: {
        url: "https://www.novelphoenix.com/novel/123/chapter/42",
        originalHtml: "<html>raw<nav>nav</nav></html>",
        originalText: "raw nav",
        html: "<div>cleaned</div>",
        text: "cleaned",
        start: "div#chapter-content",
        end: null,
      },
    });
    mockSaveSelectors.mockResolvedValue({ id: "1", result: { saved: true } });
    mockClearSelectors.mockResolvedValue({ id: "1", result: { cleared: true } });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders split tabs Original/Cleaned and mono inputs", async () => {
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="Chapter 42" chapterIndex={42} />);
    expect(screen.getByTestId("preview-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("preview-tab-original")).toBeInTheDocument();
    expect(screen.getByTestId("preview-tab-cleaned")).toBeInTheDocument();
    expect(screen.getByTestId("preview-start-input")).toBeInTheDocument();
    expect(screen.getByTestId("preview-end-input")).toBeInTheDocument();
    // aria dialog
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    // inputs have mono style (class contains mono)
    expect(screen.getByTestId("preview-start-input").className).toContain("mono");
  });

  it("live re-parse debounce 300ms calls previewChapter with custom selector", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="Title 42" chapterIndex={42} />);
    // wait for initial getSelectors + preview debounce
    await vi.advanceTimersByTimeAsync(350);
    expect(mockPreviewChapter).toHaveBeenCalled();
    mockPreviewChapter.mockClear();
    const startInput = screen.getByTestId("preview-start-input") as HTMLInputElement;
    await user.clear(startInput);
    await user.type(startInput, ".custom");
    // debounce 300ms
    await vi.advanceTimersByTimeAsync(350);
    await waitFor(() => expect(mockPreviewChapter).toHaveBeenCalled());
    const lastCall = mockPreviewChapter.mock.calls[mockPreviewChapter.mock.calls.length - 1];
    // params should contain .custom
    expect(JSON.stringify(lastCall)).toContain(".custom");
  });

  it("invalid selector shows muted error and keeps previous cleaned", async () => {
    mockPreviewChapter.mockResolvedValueOnce({
      id: "1",
      result: { originalHtml: "<html>raw</html>", originalText: "raw", html: "<div>old cleaned</div>", text: "old cleaned", start: "div#chapter-content", end: null },
    });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    expect(screen.getByTestId("preview-cleaned")).toHaveTextContent("old cleaned");
    // now invalid
    mockPreviewChapter.mockResolvedValueOnce({
      id: "1",
      error: { code: "VALUE_ERROR", message: "invalid selector: ???" },
    });
    const startInput = screen.getByTestId("preview-start-input");
    fireEvent.change(startInput, { target: { value: "???" } });
    await vi.advanceTimersByTimeAsync(350);
    await waitFor(() => expect(screen.getByTestId("preview-error")).toBeInTheDocument());
    expect(screen.getByTestId("preview-error").textContent).toContain("invalid selector");
    // previous cleaned still shown
    expect(screen.getByTestId("preview-cleaned")).toHaveTextContent("old cleaned");
  });

  it("Reset do adaptera restores default and clears override", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    const startInput = screen.getByTestId("preview-start-input") as HTMLInputElement;
    await user.clear(startInput);
    await user.type(startInput, ".novel-text");
    await vi.advanceTimersByTimeAsync(350);
    expect(startInput.value).toBe(".novel-text");
    await user.click(screen.getByTestId("preview-reset"));
    expect(mockClearSelectors).toHaveBeenCalled();
    await waitFor(() => expect(startInput.value).toBe("div#chapter-content"));
    // end should be cleared
    expect((screen.getByTestId("preview-end-input") as HTMLInputElement).value).toBe("");
  });

  it("Zastosuj saveSelectors writes override atomic and shows saved", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    const startInput = screen.getByTestId("preview-start-input");
    await user.clear(startInput);
    await user.type(startInput, ".novel-text");
    await vi.advanceTimersByTimeAsync(350);
    await user.click(screen.getByTestId("preview-save"));
    await waitFor(() => expect(mockSaveSelectors).toHaveBeenCalled());
    expect(mockSaveSelectors).toHaveBeenCalledWith(expect.objectContaining({ start: ".novel-text" }));
  });

  it("tabs switch Original/Cleaned and Esc closes", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Preview open={true} onClose={onClose} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    // initial tab is cleaned
    expect(screen.getByTestId("preview-cleaned")).toBeInTheDocument();
    await user.click(screen.getByTestId("preview-tab-original"));
    expect(screen.getByTestId("preview-original")).toBeInTheDocument();
    // Esc
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("empty isolation shows Nie wyizolowano", async () => {
    mockPreviewChapter.mockResolvedValue({
      id: "1",
      result: { originalHtml: "<html>raw</html>", originalText: "raw", html: "<div></div>", text: "", start: "div#chapter-content", end: null },
    });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    await waitFor(() => expect(screen.getByTestId("preview-empty")).toBeInTheDocument());
    expect(screen.getByTestId("preview-empty").textContent).toContain("Nie wyizolowano");
  });

  it("overlay click closes", async () => {
    const onClose = vi.fn();
    render(<Preview open={true} onClose={onClose} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(10);
    fireEvent.click(screen.getByTestId("preview-overlay"));
    expect(onClose).toHaveBeenCalled();
  });

  it("sanitizes onerror payload in rendered Cleaned tab", async () => {
    mockPreviewChapter.mockResolvedValue({
      id: "1",
      result: {
        url: "https://www.novelphoenix.com/novel/123/chapter/42",
        originalHtml: "<html>raw</html>",
        originalText: "raw",
        html: '<p>clean body</p><img src=x onerror="alert(1)">',
        text: "clean body",
        start: "div#chapter-content",
        end: null,
      },
    });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    const rendered = screen.getByTestId("preview-rendered");
    const img = rendered.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.hasAttribute("onerror")).toBe(false);
    // clean content still renders after sanitization
    expect(rendered.textContent).toContain("clean body");
  });

  it("sanitizes onerror payload in rendered Original tab", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockPreviewChapter.mockResolvedValue({
      id: "1",
      result: {
        url: "https://www.novelphoenix.com/novel/123/chapter/42",
        originalHtml: '<p>raw body</p><img src=x onerror="alert(1)" onclick="steal()">',
        originalText: "raw body",
        html: "<div>cleaned</div>",
        text: "cleaned",
        start: "div#chapter-content",
        end: null,
      },
    });
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    await user.click(screen.getByTestId("preview-tab-original"));
    const rendered = screen.getByTestId("preview-rendered");
    const img = rendered.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.hasAttribute("onerror")).toBe(false);
    expect(img?.hasAttribute("onclick")).toBe(false);
    expect(rendered.textContent).toContain("raw body");
  });

  it("clean content still renders after sanitize in default Cleaned tab", async () => {
    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
    await vi.advanceTimersByTimeAsync(350);
    const rendered = screen.getByTestId("preview-rendered");
    expect(rendered.textContent).toContain("cleaned");
    expect(rendered.querySelector("div")).not.toBeNull();
  });
});
