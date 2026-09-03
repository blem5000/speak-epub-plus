import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

vi.mock("@/lib/sidecar", () => ({
  callSidecar: vi.fn(),
  getStore: vi.fn().mockResolvedValue({ id: "0", result: { keepEPUB: true } }),
  setStore: vi.fn().mockResolvedValue({ id: "0", result: {} }),
  buildEpub: vi.fn().mockResolvedValue({ id: "0", result: { path: "dummy.epub", size: 1234, chapter_count: 1, epubcheck_ok: true, messages: [] } }),
  isEpubResult: vi.fn().mockReturnValue(true),
}));

// Must import after mock
import FindInput from "./FindInput";
import ResultsTable from "./ResultsTable";
import { useDebouncedSearch } from "@/hooks/useDebouncedSearch";
import App from "@/App";
import { callSidecar } from "@/lib/sidecar";

const mockCallSidecar = vi.mocked(callSidecar);

function Harness(): JSX.Element {
  const [q, setQ] = useState("");
  const { searching, results } = useDebouncedSearch(q, 400);
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div>
      <FindInput value={q} onChange={setQ} searching={searching} />
      {searching ? (
        <div aria-busy="true">
          <div className="h-4 animate-pulse bg-muted" />
          <div className="h-4 animate-pulse bg-muted" />
          <div className="h-4 animate-pulse bg-muted" />
          <span>Przeszukuję NovelPhoenix…</span>
        </div>
      ) : null}
      {!searching && results.length > 0 ? (
        <ResultsTable results={results} selectedUrl={selected} onSelect={setSelected} />
      ) : null}
      {!searching && q.trim() && results.length === 0 ? (
        <div>
          <p>Brak wyników dla ‘{q}’</p>
          <button type="button">Wklej URL</button>
          <a href="https://www.novelphoenix.com">fallback</a>
        </div>
      ) : null}
      {selected ? <div data-testid="selected">{selected}</div> : null}
    </div>
  );
}

describe("FindInput + debounced search (spec 1.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCallSidecar.mockReset();
  });

  it("debounce → calls search once after 400ms", async () => {
    const user = userEvent.setup({ delay: null });
    mockCallSidecar.mockResolvedValue({
      id: "1",
      result: [
        {
          site: "novelphoenix.com",
          title: "Lord of Mysteries",
          url: "https://www.novelphoenix.com/novel/123",
          link: "https://www.novelphoenix.com/novel/123",
          chapter_count: 142,
          chapters: 142,
        },
      ],
    });

    render(<Harness />);
    const input = screen.getByPlaceholderText(/Paste NovelPhoenix URL/i) as HTMLInputElement;

    // Rapid typing should debounce to single call
    await user.type(input, "lord myst");
    // Wait for debounce 400ms + microtask
    await waitFor(
      () => {
        expect(mockCallSidecar).toHaveBeenCalledTimes(1);
      },
      { timeout: 2000 }
    );
    expect(mockCallSidecar).toHaveBeenCalledWith("search", expect.objectContaining({ title: expect.any(String) }));
    const calledTitle = (mockCallSidecar.mock.calls[0][1] as { title: string }).title;
    expect(calledTitle).toContain("lord");
  });

  it("shows skeleton 3 animate-pulse with aria-busy while searching", async () => {
    const user = userEvent.setup({ delay: null });
    // Make callSidecar pending to keep searching true
    let resolve!: (v: unknown) => void;
    mockCallSidecar.mockReturnValue(
      new Promise((res) => {
        resolve = res as unknown as (v: unknown) => void;
      }) as unknown as ReturnType<typeof mockCallSidecar>
    );

    render(<Harness />);
    const input = screen.getByPlaceholderText(/Paste NovelPhoenix URL/i);
    await user.type(input, "Lord of Mysteries");

    // After debounce, searching should be true and skeleton appears
    await waitFor(
      () => {
        const busy = document.querySelector('[aria-busy="true"]');
        expect(busy).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
    const pulses = document.querySelectorAll(".animate-pulse");
    expect(pulses.length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/Przeszukuję/)).toBeInTheDocument();

    // cleanup: resolve promise to not hang
    resolve({ id: "1", result: [] });
    await waitFor(() => {
      const busy = document.querySelector('[aria-busy="true"]');
      expect(busy).not.toBeInTheDocument();
    });
  });

  it("no-results shows display-sm + CTA Wklej URL + link fallback", async () => {
    const user = userEvent.setup({ delay: null });
    mockCallSidecar.mockResolvedValue({ id: "1", result: [] });

    render(<Harness />);
    const input = screen.getByPlaceholderText(/Paste NovelPhoenix URL/i);
    await user.type(input, "zzzz_no_match");

    await waitFor(
      () => {
        expect(screen.getByText(/Brak wyników dla/)).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
    expect(screen.getByText("Wklej URL")).toBeInTheDocument();
    expect(screen.getByText("fallback")).toBeInTheDocument();
  });

  it("keyboard Enter wybiera row - roving tabindex", async () => {
    const onSelect = vi.fn();
    const results = [
      {
        site: "novelphoenix.com",
        title: "Lord of Mysteries",
        url: "https://www.novelphoenix.com/novel/123",
        link: "https://www.novelphoenix.com/novel/123",
        chapter_count: 142,
        chapters: 142,
      },
      {
        site: "novelphoenix.com",
        title: "Other Title",
        url: "https://www.novelphoenix.com/novel/456",
        link: "https://www.novelphoenix.com/novel/456",
        chapter_count: null,
        chapters: null,
      },
    ];
    render(<ResultsTable results={results} selectedUrl={null} onSelect={onSelect} />);

    const rows = screen.getAllByRole("button");
    expect(rows.length).toBe(2);
    // roving tabindex: first row tabIndex 0, second -1
    expect(rows[0]).toHaveAttribute("tabIndex", "0");
    expect(rows[1]).toHaveAttribute("tabIndex", "-1");
    // hover muted vs selected accent check: initial not selected
    expect(rows[0].className).toContain("hover:bg-muted");
    expect(rows[0]).toHaveAttribute("aria-selected", "false");

    // Focus first row and press Enter to select
    rows[0].focus();
    expect(document.activeElement).toBe(rows[0]);
    fireEvent.keyDown(rows[0], { key: "Enter", code: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("https://www.novelphoenix.com/novel/123");

    // ArrowDown should move focus to second row (roving)
    fireEvent.keyDown(rows[0], { key: "ArrowDown", code: "ArrowDown" });
    await waitFor(() => {
      expect(document.activeElement).toBe(rows[1]);
    });
    expect(rows[1]).toHaveAttribute("tabIndex", "0");

    // Now select second via Enter
    fireEvent.keyDown(rows[1], { key: "Enter", code: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("https://www.novelphoenix.com/novel/456");

    // Render selected state → theme-aware accent tint (readable light + dark) and border-accent
    render(<ResultsTable results={results} selectedUrl={results[0].url} onSelect={onSelect} />);
    const selectedRow = screen.getAllByRole("button").find((r) => r.getAttribute("aria-selected") === "true");
    expect(selectedRow).toBeDefined();
    expect(selectedRow?.className).toContain("bg-accent/15");
    expect(selectedRow?.className).toContain("text-foreground");
    expect(selectedRow?.className).toContain("border-accent");
    expect(selectedRow?.className).toContain("border-l-2");
    expect(selectedRow?.className).toContain("border-accent");
    expect(selectedRow?.className).toContain("border-l-2");
  });

  it("App wires FindInput + ResultsTable with header and no hardcode", async () => {
    mockCallSidecar.mockResolvedValue({
      id: "1",
      result: [
        {
          site: "novelphoenix.com",
          title: "Lord of Mysteries",
          url: "https://www.novelphoenix.com/novel/123",
          link: "https://www.novelphoenix.com/novel/123",
          chapter_count: 142,
        },
      ],
    });
    render(<App />);
    // FindInput via data-testid (token demo has duplicate placeholder, so use testId)
    const input = screen.getByTestId("find-input");
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("placeholder", expect.stringContaining("Paste"));
    // h-11 class check (44px per spec)
    expect(input.className).toContain("h-11");
    expect(input.className).toContain("focus-visible:ring-2");
    // Header switch still present
    expect(screen.getByText("Speak EPUB")).toBeInTheDocument();
    // Type and see results eventually
    const user = userEvent.setup({ delay: null });
    await user.type(input, "Lord");
    await waitFor(
      () => {
        expect(screen.getByText("Lord of Mysteries")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );
  });
});
