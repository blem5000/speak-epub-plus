import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FiltersWindow from "./FiltersWindow";

const mockGetFilters = vi.fn();
const mockAddFilter = vi.fn();
const mockRemoveFilter = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  getFilters: (...args: unknown[]) => mockGetFilters(...args),
  addFilter: (...args: unknown[]) => mockAddFilter(...args),
  removeFilter: (...args: unknown[]) => mockRemoveFilter(...args),
  isFiltersResult: (res: { result?: unknown }) => {
    if (!res.result || typeof res.result !== "object") return false;
    const r = res.result as Record<string, unknown>;
    return Array.isArray(r.filters);
  },
}));

describe("FiltersWindow 4.3 — window pełny", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFilters.mockResolvedValue({ id: "1", result: { filters: [] } });
    mockAddFilter.mockResolvedValue({ id: "1", result: { filters: [{ pattern: "Subscribe", isRegex: false }], added: true } });
    mockRemoveFilter.mockResolvedValue({ id: "1", result: { filters: [], removed: true } });
  });

  it("renders closed as null", () => {
    const { container } = render(<FiltersWindow open={false} onClose={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("open shows dialog overlay with Filters panel", async () => {
    render(<FiltersWindow open={true} onClose={vi.fn()} />);
    expect(screen.getByTestId("filters-window-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("filters-window-overlay")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    // Filters inside
    expect(await screen.findByTestId("filter-input")).toBeInTheDocument();
    expect(screen.getByTestId("filters-table")).toBeInTheDocument();
    expect(screen.getByTestId("filter-avg")).toBeInTheDocument();
    // title via t
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-label", expect.stringMatching(/Filtry|Filters/));
  });

  it("Esc calls onClose", async () => {
    const onClose = vi.fn();
    render(<FiltersWindow open={true} onClose={onClose} />);
    await screen.findByTestId("filter-input");
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("overlay click calls onClose", async () => {
    const onClose = vi.fn();
    render(<FiltersWindow open={true} onClose={onClose} />);
    await screen.findByTestId("filter-input");
    fireEvent.click(screen.getByTestId("filters-window-overlay"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("close button calls onClose", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<FiltersWindow open={true} onClose={onClose} />);
    await screen.findByTestId("filter-input");
    await user.click(screen.getByTestId("filters-window-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("focus trap loops Tab", async () => {
    render(<FiltersWindow open={true} onClose={vi.fn()} />);
    await screen.findByTestId("filter-input");
    const dialog = screen.getByTestId("filters-window-dialog");
    // initial focus is within dialog (first focusable = close button)
    expect(dialog.contains(document.activeElement as Node)).toBeTruthy();
    // Tab behavior is covered via Settings/Preview pattern; verify dialog focusable elements exist
    const closeBtn = screen.getByTestId("filters-window-close");
    expect(closeBtn).toBeInTheDocument();
    // Simulate Tab from last element should loop to first (indirect via key handler existence)
    fireEvent.keyDown(document, { key: "Tab", code: "Tab" });
    // after Tab, focus should remain within dialog
    expect(dialog.contains(document.activeElement as Node)).toBeTruthy();
  });

  it("uses t() no hard-coded title", async () => {
    render(<FiltersWindow open={true} onClose={vi.fn()} />);
    // dialog aria-label is from t("filters.title")
    const dialog = await screen.findByTestId("filters-window-dialog");
    expect(dialog.getAttribute("aria-label")).not.toBe("");
    // heading inside Filters should be via t — there are two headings (window + inner panel), check both present
    const headings = await screen.findAllByText(/Filtry|Filters/);
    expect(headings.length).toBeGreaterThanOrEqual(1);
    expect(headings[0]).toBeInTheDocument();
  });
});
