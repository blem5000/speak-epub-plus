import { describe, it, expect } from "vitest";
import { selectedUrlsForFetch } from "./selection";

const ch = (index: number) => ({ index, url: `https://www.novelphoenix.com/novel/123/chapter/${index}` });

describe("selectedUrlsForFetch", () => {
  it("checkbox selection wins over range", () => {
    const list = [ch(1), ch(2), ch(3), ch(4), ch(5)];
    expect(selectedUrlsForFetch(list, new Set([2, 4]), 1, 5)).toEqual([ch(2).url, ch(4).url]);
  });

  it("contiguous range matches by position (= index)", () => {
    const list = [ch(1), ch(2), ch(3), ch(4), ch(5)];
    const urls = selectedUrlsForFetch(list, new Set(), 2, 4);
    expect(urls).toEqual([ch(2).url, ch(3).url, ch(4).url]);
  });

  it("single-chapter sparse list never yields [] (Build EPUB dead click)", () => {
    const list = [ch(57)];
    // from/to defaults 1..30 against index 57 — positional slice still returns it
    expect(selectedUrlsForFetch(list, new Set(), 1, 30)).toEqual([ch(57).url]);
    expect(selectedUrlsForFetch(list, new Set(), 1, 1)).toEqual([ch(57).url]);
  });

  it("swapped and out-of-bounds ranges clamp positionally", () => {
    const list = [ch(10), ch(20), ch(30)];
    expect(selectedUrlsForFetch(list, new Set(), 3, 1)).toEqual([ch(10).url, ch(20).url, ch(30).url]);
    expect(selectedUrlsForFetch(list, new Set(), 1, 999)).toEqual([ch(10).url, ch(20).url, ch(30).url]);
  });

  it("empty list → []", () => {
    expect(selectedUrlsForFetch([], new Set(), 1, 30)).toEqual([]);
  });
});
