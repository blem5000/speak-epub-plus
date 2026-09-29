import { describe, it, expect, vi } from "vitest";
import {
  normalizeVersion,
  parseVersionParts,
  compareVersions,
  fetchLatestRelease,
  checkForUpdates,
} from "./updater";

function mockFetch(json: unknown, ok = true): typeof fetch {
  return vi.fn().mockResolvedValue({
    ok,
    json: () => Promise.resolve(json),
  }) as unknown as typeof fetch;
}

describe("updater versions", () => {
  it("normalize strips v and build metadata", () => {
    expect(normalizeVersion("v0.1.4")).toBe("0.1.4");
    expect(normalizeVersion("  V1.2.3+build ")).toBe("1.2.3");
    expect(normalizeVersion("0.2.0")).toBe("0.2.0");
  });

  it("parse handles suffixes as numeric prefix", () => {
    expect(parseVersionParts("v0.1.4")).toEqual([0, 1, 4]);
    expect(parseVersionParts("1.2-beta")).toEqual([1, 2]);
  });

  it("compare detects newer/older/equal", () => {
    expect(compareVersions("0.1.4", "v0.2.0")).toBe(-1);
    expect(compareVersions("0.2.0", "0.2.0")).toBe(0);
    expect(compareVersions("0.3.0", "0.2.0")).toBe(1);
    expect(compareVersions("0.1.4", "0.1.4")).toBe(0);
  });
});

describe("checkForUpdates", () => {
  it("returns info when latest is newer", async () => {
    const fetchFn = mockFetch({ tag_name: "v0.2.0", html_url: "https://example/r", body: "notes" });
    const info = await checkForUpdates("0.1.4", fetchFn);
    expect(info?.available).toBe(true);
    expect(info?.latest).toBe("0.2.0");
    expect(info?.url).toBe("https://example/r");
  });

  it("returns null when up to date", async () => {
    const fetchFn = mockFetch({ tag_name: "v0.1.4", html_url: "https://example/r" });
    expect(await checkForUpdates("0.1.4", fetchFn)).toBeNull();
  });

  it("returns null on http error or bad shape (silent)", async () => {
    expect(await checkForUpdates("0.1.4", mockFetch({}, false))).toBeNull();
    expect(await checkForUpdates("0.1.4", mockFetch({ nope: 1 }))).toBeNull();
    const throwing = vi.fn().mockRejectedValue(new Error("net")) as unknown as typeof fetch;
    expect(await checkForUpdates("0.1.4", throwing)).toBeNull();
  });

  it("fetchLatestRelease returns null on throw", async () => {
    const throwing = vi.fn().mockRejectedValue(new Error("net")) as unknown as typeof fetch;
    expect(await fetchLatestRelease(throwing)).toBeNull();
  });
});
