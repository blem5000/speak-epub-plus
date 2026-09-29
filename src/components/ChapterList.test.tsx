import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import ChapterList from "./ChapterList";
import type { ChapterInfo } from "@/hooks/useChapterList";
import { clamp, rangeToSet, toggleSet, bulkShift } from "@/lib/selection";

vi.mock("@/lib/sidecar", () => ({
  callSidecar: vi.fn().mockResolvedValue({ id: "1", result: [] }),
}));

function make142(): ChapterInfo[] {
  return Array.from({ length: 142 }, (_, i) => ({
    index: i + 1,
    title: `Chapter ${i + 1}: Title ${i + 1}`,
    url: `https://www.novelphoenix.com/novel/123/chapter/${i + 1}`,
  }));
}

function make800(): ChapterInfo[] {
  return Array.from({ length: 800 }, (_, i) => ({
    index: i + 1,
    title: `Chapter ${i + 1}`,
    url: `https://www.novelphoenix.com/novel/123/chapter/${i + 1}`,
  }));
}

function Harness({
  initialChapters = make142(),
  initialFrom = 1,
  initialTo = 30,
  initialSelected = new Set<number>(),
  initialAnchor = null as number | null,
  onPreviewMock,
  onStartFetchMock,
}: {
  initialChapters?: ChapterInfo[];
  initialFrom?: number;
  initialTo?: number;
  initialSelected?: Set<number>;
  initialAnchor?: number | null;
  onPreviewMock?: ReturnType<typeof vi.fn>;
  onStartFetchMock?: ReturnType<typeof vi.fn>;
}) {
  const [chapters] = useState(initialChapters);
  const [selected, setSelected] = useState<Set<number>>(initialSelected);
  const [from, setFrom] = useState(initialFrom);
  const [to, setTo] = useState(initialTo);
  const [anchor, setAnchor] = useState<number | null>(initialAnchor);
  const preview = onPreviewMock ?? vi.fn();
  const startFetch = onStartFetchMock ?? vi.fn();
  return (
    <ChapterList
      chapters={chapters}
      selected={selected}
      from={from}
      to={to}
      anchor={anchor}
      busy={false}
      onSelectedChange={setSelected}
      onRangeChange={(a, b) => {
        setFrom(a);
        setTo(b);
      }}
      onAnchorChange={setAnchor}
      onStartFetch={startFetch}
      onPreview={preview}
    />
  );
}

function expandList(): void {
  fireEvent.click(screen.getByTestId("chapter-list-toggle"));
}

describe("ChapterList 1.4 - selection helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("clamp 1..N handles swap and empty", () => {
    expect(clamp(0, 1, 142)).toBe(1);
    expect(clamp(200, 1, 142)).toBe(142);
    expect(clamp(5, 1, 142)).toBe(5);
    expect(clamp(NaN as unknown as number, 1, 142)).toBe(1);
    let s = rangeToSet(0, 200, 142);
    expect(s.size).toBe(142);
    expect(s.has(1)).toBe(true);
    expect(s.has(142)).toBe(true);
    s = rangeToSet(30, 1, 142);
    expect(s.size).toBe(30);
    expect(s.has(1)).toBe(true);
    expect(s.has(30)).toBe(true);
    s = rangeToSet("abc", 10, 142);
    expect(s.size).toBe(0);
    s = rangeToSet("", 10, 142);
    expect(s.size).toBe(0);
  });

  it("lista domyślnie zwinięta, toggle pokazuje liczbę", () => {
    render(<Harness initialFrom={1} initialTo={30} />);
    expect(screen.queryByTestId("chapter-row-1")).toBeNull();
    const toggle = screen.getByTestId("chapter-list-toggle");
    expect(toggle.textContent).toMatch(/142/);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByTestId("chapter-row-1")).toBeInTheDocument();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("Start 1-30 →30 checkboxów zaznaczonych, label Wybrano 30 z 142, fetch z zakresem", async () => {
    const user = userEvent.setup();
    const onStartFetch = vi.fn();
    render(<Harness initialFrom={1} initialTo={30} onStartFetchMock={onStartFetch} />);
    expandList();
    expect(screen.getByTestId("selected-label").textContent).toMatch(/0/);
    const btn = screen.getByTestId("range-start");
    await user.click(btn);
    const checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    const checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(30);
    const label = screen.getByTestId("selected-label");
    expect(label.textContent).toMatch(/30/);
    expect(label.textContent).toMatch(/142/);
    const row1 = screen.getByTestId("chapter-row-1");
    expect(row1.className).toContain("border-accent");
    expect(row1.className).toContain("bg-accent/10");
    expect(onStartFetch).toHaveBeenCalledWith(1, 30);
  });

  it("clamp od<1→1 do>N→N swap works via RangeBar", async () => {
    const user = userEvent.setup();
    const onStartFetch = vi.fn();
    render(<Harness initialFrom={0} initialTo={999} onStartFetchMock={onStartFetch} />);
    expandList();
    const fromInput = screen.getByTestId("range-from") as HTMLInputElement;
    const toInput = screen.getByTestId("range-to") as HTMLInputElement;
    fireEvent.change(fromInput, { target: { value: "0" } });
    fireEvent.blur(fromInput);
    await waitFor(() => {
      expect((screen.getByTestId("range-from") as HTMLInputElement).value).toBe("1");
    });
    fireEvent.change(toInput, { target: { value: "999" } });
    fireEvent.blur(toInput);
    await waitFor(() => {
      expect((screen.getByTestId("range-to") as HTMLInputElement).value).toBe("142");
    });
    await user.click(screen.getByTestId("range-start"));
    const checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    const checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(142);
    expect(onStartFetch).toHaveBeenCalledWith(1, 142);
  });

  it("typing From above To keeps user order on blur (no swap)", async () => {
    render(<Harness initialFrom={1} initialTo={30} />);
    const fromInput = screen.getByTestId("range-from") as HTMLInputElement;
    // user replaces 1 with 92, intending to type the upper bound next
    fireEvent.change(fromInput, { target: { value: "92" } });
    fireEvent.blur(fromInput);
    await waitFor(() => {
      expect((screen.getByTestId("range-from") as HTMLInputElement).value).toBe("92");
    });
    // To untouched — must NOT become 92 with From rewritten to 30
    expect((screen.getByTestId("range-to") as HTMLInputElement).value).toBe("30");
  });

  it("focusing a range field selects its content (no Ctrl+A needed)", async () => {
    render(<Harness initialFrom={1} initialTo={30} />);
    const fromInput = screen.getByTestId("range-from") as HTMLInputElement;
    fireEvent.focus(fromInput);
    expect(fromInput.selectionStart).toBe(0);
    expect(fromInput.selectionEnd).toBe(fromInput.value.length);
    expect(fromInput.value.length).toBeGreaterThan(0);
    const toInput = screen.getByTestId("range-to") as HTMLInputElement;
    fireEvent.focus(toInput);
    expect(toInput.selectionStart).toBe(0);
    expect(toInput.selectionEnd).toBe(toInput.value.length);
  });

  it("ArrowUp/Down steps the focused range field by 1", async () => {
    render(<Harness initialFrom={30} initialTo={70} />);
    const fromInput = screen.getByTestId("range-from") as HTMLInputElement;
    fireEvent.keyDown(fromInput, { key: "ArrowUp", code: "ArrowUp" });
    await waitFor(() => {
      expect((screen.getByTestId("range-from") as HTMLInputElement).value).toBe("31");
    });
    fireEvent.keyDown(fromInput, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.keyDown(fromInput, { key: "ArrowDown", code: "ArrowDown" });
    await waitFor(() => {
      expect((screen.getByTestId("range-from") as HTMLInputElement).value).toBe("29");
    });
  });

  it("type 50 without blur + Start fetches typed range (no stale props)", async () => {
    const onStartFetch = vi.fn();
    render(<Harness initialFrom={1} initialTo={30} onStartFetchMock={onStartFetch} />);
    expandList();
    const fromInput = screen.getByTestId("range-from") as HTMLInputElement;
    // type without blurring — the Start button must use field values, not props
    fireEvent.change(fromInput, { target: { value: "50" } });
    fireEvent.click(screen.getByTestId("range-start"));
    await waitFor(() => {
      expect(screen.getByTestId("selected-label").textContent).toMatch(/21/);
    });
    const checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    const checked = checks.filter((c) => c.checked);
    // committed 50..30 → swap → 30..50 = 21 chapters
    expect(checked.length).toBe(21);
    expect(onStartFetch).toHaveBeenCalledWith(30, 50);
  });

  it("type + Enter starts typed range without blur", async () => {
    const onStartFetch = vi.fn();
    render(<Harness initialFrom={1} initialTo={30} onStartFetchMock={onStartFetch} />);
    expandList();
    const toInput = screen.getByTestId("range-to") as HTMLInputElement;
    fireEvent.change(toInput, { target: { value: "10" } });
    fireEvent.keyDown(toInput, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      expect(screen.getByTestId("selected-label").textContent).toMatch(/10/);
    });
    const checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    const checked = checks.filter((c) => c.checked);
    // committed 1..10 = 10 chapters (not stale 1..30)
    expect(checked.length).toBe(10);
    expect(onStartFetch).toHaveBeenCalledWith(1, 10);
  });

  it("Shift 10→40 bulk select adds range", async () => {
    const initialSel = new Set<number>();
    for (let i = 1; i <= 30; i++) initialSel.add(i);
    render(<Harness initialSelected={initialSel} initialAnchor={10} />);
    expandList();
    let checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    let checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(30);
    const row40 = screen.getByTestId("chapter-row-40");
    fireEvent.click(row40, { shiftKey: true });
    checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(40);
    expect(screen.getByTestId("selected-label").textContent).toMatch(/40/);
    const s = bulkShift(10, 40, initialSel);
    expect(s.size).toBe(40);
    expect(s.has(35)).toBe(true);
    expect(s.has(40)).toBe(true);
  });

  it("Shift bez anchor → single toggle", async () => {
    render(<Harness initialSelected={new Set()} initialAnchor={null} />);
    expandList();
    const row5 = screen.getByTestId("chapter-row-5");
    fireEvent.click(row5, { shiftKey: true });
    const checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    const checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(1);
    expect(checked[0].getAttribute("aria-label")).toMatch(/5/);
  });

  it("double-click row 5 → onPreview emit, hover eye visible", async () => {
    const onPreview = vi.fn();
    render(<Harness onPreviewMock={onPreview} />);
    expandList();
    const row5 = screen.getByTestId("chapter-row-5");
    expect(row5.textContent).toContain("👁");
    fireEvent.doubleClick(row5);
    expect(onPreview).toHaveBeenCalledWith(5);
  });

  it("keyboard Space toggle, Ctrl+A select all, arrows roving, Esc nie zamyka", async () => {
    render(<Harness />);
    expandList();
    const rows = Array.from(document.querySelectorAll('[data-testid^="chapter-row-"]')) as HTMLElement[];
    const first = rows[0];
    const second = rows[1];
    expect(first).toHaveAttribute("tabIndex", "0");
    expect(second).toHaveAttribute("tabIndex", "-1");
    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: " ", code: "Space", keyCode: 32 });
    let checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    let checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(1);
    fireEvent.keyDown(first, { key: "ArrowDown", code: "ArrowDown" });
    await waitFor(() => {
      expect(document.activeElement).toBe(second);
    });
    expect(second).toHaveAttribute("tabIndex", "0");
    fireEvent.keyDown(second, { key: "End", code: "End" });
    await waitFor(() => {
      const allRows = Array.from(document.querySelectorAll('[data-testid^="chapter-row-"]')) as HTMLElement[];
      const last = allRows[allRows.length - 1];
      expect(document.activeElement).toBe(last);
    });
    const allRows = Array.from(document.querySelectorAll('[data-testid^="chapter-row-"]')) as HTMLElement[];
    const last = allRows[allRows.length - 1];
    fireEvent.keyDown(last, { key: "Home", code: "Home" });
    await waitFor(() => {
      expect(document.activeElement).toBe(allRows[0]);
    });
    const container = screen.getByRole("region");
    fireEvent.keyDown(container, { key: "a", code: "KeyA", ctrlKey: true });
    checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    checked = checks.filter((c) => c.checked);
    expect(checked.length).toBe(142);
    expect(screen.getByTestId("selected-label").textContent).toMatch(/142/);
    fireEvent.keyDown(allRows[0], { key: "Escape", code: "Escape" });
    expect(screen.getByRole("region")).toBeInTheDocument();
    expect(allRows[0].getAttribute("aria-selected")).toBe("true");
    expect(allRows[0].className).toContain("focus-visible:ring-2");
  });

  it("virtualized >500 fallback shows warning but still renders", async () => {
    const chapters800 = make800();
    render(<Harness initialChapters={chapters800} initialFrom={1} initialTo={10} />);
    expandList();
    expect(screen.getByTestId("virtualized-warning")).toBeInTheDocument();
    expect(screen.getByTestId("virtualized-warning").textContent).toMatch(/800/);
    expect(screen.getByTestId("chapter-row-1")).toBeInTheDocument();
    const header = document.querySelector("thead.sticky");
    expect(header).not.toBeNull();
    expect(header?.className).toContain("sticky");
  });

  it("Start replaces previous selection with typed range", async () => {
    const user = userEvent.setup();
    const onStartFetch = vi.fn();
    const initialSel = new Set<number>();
    for (let i = 1; i <= 5; i++) initialSel.add(i);
    render(<Harness initialSelected={initialSel} initialFrom={10} initialTo={12} onStartFetchMock={onStartFetch} />);
    expandList();
    let checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checks.filter((c) => c.checked).length).toBe(5);
    await user.click(screen.getByTestId("range-start"));
    checks = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checks.filter((c) => c.checked).length).toBe(3);
    expect(screen.getByTestId("selected-label").textContent).toMatch(/3/);
    expect(onStartFetch).toHaveBeenCalledWith(10, 12);
  });

  it("toggleSet and clamp helpers pure", () => {
    const s = new Set([1, 2, 3]);
    const t1 = toggleSet(s, 2);
    expect(t1.has(2)).toBe(false);
    expect(t1.has(1)).toBe(true);
    const t2 = toggleSet(t1, 4);
    expect(t2.has(4)).toBe(true);
  });
});
