import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Filters from "./Filters";

const mockGetFilters = vi.fn();
const mockAddFilter = vi.fn();
const mockRemoveFilter = vi.fn();
const mockSaveFilters = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  getFilters: (...args: unknown[]) => mockGetFilters(...args),
  addFilter: (...args: unknown[]) => mockAddFilter(...args),
  removeFilter: (...args: unknown[]) => mockRemoveFilter(...args),
  saveFilters: (...args: unknown[]) => mockSaveFilters(...args),
  isFiltersResult: (res: { result?: unknown }) => {
    if (!res.result || typeof res.result !== "object") return false;
    const r = res.result as Record<string, unknown>;
    return Array.isArray(r.filters);
  },
}));

describe("Filters 2.3 — plain+regex gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetFilters.mockResolvedValue({ id: "1", result: { filters: [] } });
    mockAddFilter.mockImplementation(async (_p: unknown) => {
      // simulate server adds and returns updated list
      return { id: "1", result: { filters: [{ pattern: "Subscribe", isRegex: false }], added: true } };
    });
    mockRemoveFilter.mockImplementation(async () => ({ id: "1", result: { filters: [], removed: true } }));
    mockSaveFilters.mockResolvedValue({ id: "1", result: { filters: [], saved: true } });
  });

  it("renders empty state and input + toggle", async () => {
    render(<Filters />);
    expect(await screen.findByTestId("filter-input")).toBeInTheDocument();
    expect(screen.getByTestId("filter-regex-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("filter-add")).toBeInTheDocument();
    expect(await screen.findByTestId("filters-table")).toHaveTextContent(/Brak filtrów|No filters/);
    expect(screen.getByTestId("filter-avg")).toBeInTheDocument();
  });

  it("add plain filter updates table and avg", async () => {
    mockGetFilters.mockResolvedValueOnce({ id: "1", result: { filters: [] } });
    mockAddFilter.mockResolvedValueOnce({
      id: "1",
      result: { filters: [{ pattern: "Subscribe", isRegex: false }], added: true },
    });
    const user = userEvent.setup();
    render(<Filters />);
    await screen.findByTestId("filter-input");
    const input = screen.getByTestId("filter-input") as HTMLInputElement;
    await user.type(input, "Subscribe");
    await user.click(screen.getByTestId("filter-add"));
    await waitFor(() => expect(mockAddFilter).toHaveBeenCalledWith({ pattern: "Subscribe", isRegex: false }));
    await waitFor(() => expect(screen.getByTestId("filters-table")).toHaveTextContent("Subscribe"));
    expect(screen.getByTestId("filter-type-0").textContent).toContain("plain");
    // avg should update to non-zero (EN or PL)
    expect(screen.getByTestId("filter-avg").textContent).toMatch(/usuwa średnio|removes ~|lines\/chapter/);
  });

  it("add regex filter validates and shows badge", async () => {
    mockGetFilters.mockResolvedValueOnce({ id: "1", result: { filters: [] } });
    mockAddFilter.mockResolvedValueOnce({
      id: "1",
      result: { filters: [{ pattern: "subscribe.*patreon", isRegex: true }], added: true },
    });
    const user = userEvent.setup();
    render(<Filters />);
    await screen.findByTestId("filter-input");
    await user.type(screen.getByTestId("filter-input"), "subscribe.*patreon");
    await user.click(screen.getByTestId("filter-regex-toggle"));
    await user.click(screen.getByTestId("filter-add"));
    await waitFor(() => expect(mockAddFilter).toHaveBeenCalledWith({ pattern: "subscribe.*patreon", isRegex: true }));
    await waitFor(() => expect(screen.getByTestId("filter-type-0").textContent).toContain("regex"));
  });

  it("invalid regex shows muted error and does not call sidecar", async () => {
    const user = userEvent.setup();
    render(<Filters />);
    await screen.findByTestId("filter-input");
    const input = screen.getByTestId("filter-input") as HTMLInputElement;
    // use fireEvent to avoid userEvent keyboard parsing of "[" 
    fireEvent.change(input, { target: { value: "[*" } });
    await user.click(screen.getByTestId("filter-regex-toggle"));
    await user.click(screen.getByTestId("filter-add"));
    await waitFor(() => expect(screen.getByTestId("filter-error")).toBeInTheDocument());
    expect(screen.getByTestId("filter-error").textContent).toMatch(/invalid regex|Invalid regular/i);
    expect(mockAddFilter).not.toHaveBeenCalled();
  });

  it("duplicate blocked shows error", async () => {
    mockGetFilters.mockResolvedValueOnce({
      id: "1",
      result: { filters: [{ pattern: "Subscribe", isRegex: false }] },
    });
    const user = userEvent.setup();
    render(<Filters />);
    await screen.findByTestId("filters-table");
    expect(screen.getByTestId("filter-type-0")).toBeInTheDocument();
    await user.type(screen.getByTestId("filter-input"), "Subscribe");
    await user.click(screen.getByTestId("filter-add"));
    await waitFor(() => expect(screen.getByTestId("filter-error")).toBeInTheDocument());
    expect(screen.getByTestId("filter-error").textContent).toMatch(/Duplikat|Duplicate/);
  });

  it("delete removes row", async () => {
    mockGetFilters.mockResolvedValueOnce({
      id: "1",
      result: { filters: [{ pattern: "Subscribe", isRegex: false }, { pattern: "patreon", isRegex: false }] },
    });
    mockRemoveFilter.mockResolvedValueOnce({
      id: "1",
      result: { filters: [{ pattern: "patreon", isRegex: false }], removed: true },
    });
    const user = userEvent.setup();
    render(<Filters />);
    await screen.findByTestId("filter-delete-0");
    expect(screen.getByText("Subscribe")).toBeInTheDocument();
    await user.click(screen.getByTestId("filter-delete-0"));
    await waitFor(() => expect(mockRemoveFilter).toHaveBeenCalledWith({ index: 0 }));
    await waitFor(() => expect(screen.queryByText("Subscribe")).not.toBeInTheDocument());
  });

  it("avg live updates with filters count", async () => {
    mockGetFilters
      .mockResolvedValueOnce({ id: "1", result: { filters: [] } })
      .mockResolvedValueOnce({ id: "1", result: { filters: [{ pattern: "Subscribe", isRegex: false }] } });
    mockAddFilter.mockResolvedValueOnce({
      id: "1",
      result: {
        filters: [
          { pattern: "Subscribe", isRegex: false },
          { pattern: "Unlimited access", isRegex: false },
        ],
        added: true,
      },
    });
    const user = userEvent.setup();
    render(<Filters />);
    const avg0 = (await screen.findByTestId("filter-avg")).textContent;
    await user.type(screen.getByTestId("filter-input"), "Unlimited access");
    await user.click(screen.getByTestId("filter-add"));
    await waitFor(() => expect(mockAddFilter).toHaveBeenCalled());
    // after add, filters length 2, avg should be > previous
    await waitFor(() => {
      const txt = screen.getByTestId("filter-avg").textContent;
      expect(txt).toMatch(/usuwa średnio|removes ~|lines\/chapter/);
    });
    expect(screen.getByTestId("filter-avg").textContent).not.toEqual(avg0);
  });
});
