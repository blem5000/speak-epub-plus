import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SearchHistory from "./SearchHistory";
import LibraryPanel from "./LibraryPanel";
import PronunciationEditor from "./PronunciationEditor";

describe("SearchHistory", () => {
  it("is hidden when there is no history", () => {
    render(<SearchHistory entries={[]} onPick={vi.fn()} onClear={vi.fn()} />);
    expect(screen.queryByTestId("search-history")).not.toBeInTheDocument();
  });

  it("runs a remembered search again and can be cleared", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    const onClear = vi.fn();
    render(
      <SearchHistory
        entries={[{ query: "Wiedzmin", at: 1 }, { query: "Zamkniete Drzwi", at: 2 }]}
        onPick={onPick}
        onClear={onClear}
      />
    );
    await user.click(screen.getByTestId("search-history-Wiedzmin"));
    expect(onPick).toHaveBeenCalledWith("Wiedzmin");
    await user.click(screen.getByTestId("search-history-clear"));
    expect(onClear).toHaveBeenCalled();
  });
});

describe("LibraryPanel", () => {
  const entry = {
    id: "1",
    title: "Wiedzmin",
    author: "Sapkowski",
    cover: "https://x.test/cover.jpg",
    path: "C:/out/wiedzmin.m4b",
    format: "m4b",
    size: 12 * 1024 * 1024,
    chapters: 12,
    sourceUrl: "https://x.test/novel",
    createdAt: 1,
  };

  it("is hidden when the library is empty", () => {
    render(<LibraryPanel entries={[]} onOpen={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.queryByTestId("library-panel")).not.toBeInTheDocument();
  });

  it("lists the audiobooks and opens / forgets one", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onRemove = vi.fn();
    render(<LibraryPanel entries={[entry]} onOpen={onOpen} onRemove={onRemove} />);
    expect(screen.getByText("Wiedzmin")).toBeInTheDocument();
    expect(screen.getByText("Sapkowski")).toBeInTheDocument();
    await user.click(screen.getByTestId("library-open-C:/out/wiedzmin.m4b"));
    expect(onOpen).toHaveBeenCalledWith("C:/out/wiedzmin.m4b");
    await user.click(screen.getByTestId("library-remove-C:/out/wiedzmin.m4b"));
    expect(onRemove).toHaveBeenCalledWith("C:/out/wiedzmin.m4b");
  });
});

describe("PronunciationEditor", () => {
  it("adds a word with its reading", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PronunciationEditor entries={[]} onChange={onChange} />);
    await user.type(screen.getByTestId("pronunciation-from"), "Arystoteles");
    await user.type(screen.getByTestId("pronunciation-to"), "ary-stoteles");
    await user.click(screen.getByTestId("pronunciation-add"));
    expect(onChange).toHaveBeenCalledWith([{ from: "Arystoteles", to: "ary-stoteles" }]);
  });

  it("complains when a field is missing", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PronunciationEditor entries={[]} onChange={onChange} />);
    await user.type(screen.getByTestId("pronunciation-from"), "Arystoteles");
    await user.click(screen.getByTestId("pronunciation-add"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("pronunciation-error")).toBeInTheDocument();
  });

  it("removes a word", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PronunciationEditor entries={[{ from: "Jan", to: "Yahn" }]} onChange={onChange} />
    );
    await user.click(screen.getByTestId("pronunciation-remove-Jan"));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
