import { describe, it, expect, vi, beforeEach } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  announceUpdateFound,
  canInstallUpdates,
  checkForUpdates,
  normalizeVersion,
  onUpdateFound,
  parseVersionParts,
  compareVersions,
  fetchLatestRelease,
  getUpdatePrefs,
  skipVersion,
  downloadUpdate,
  type UpdateInfo,
} from "./updater";
import { getStore, setStore } from "@/lib/sidecar";

vi.mock("@/lib/sidecar", () => ({
  getStore: vi.fn(),
  setStore: vi.fn(),
}));

const mockedGetStore = vi.mocked(getStore);
const mockedSetStore = vi.mocked(setStore);
const mockedInvoke = vi.mocked(invoke);
const mockedListen = vi.mocked(listen);

function mockFetch(json: unknown, ok = true): typeof fetch {
  return vi.fn().mockResolvedValue({
    ok,
    json: () => Promise.resolve(json),
  }) as unknown as typeof fetch;
}

const RELEASE_WITH_ASSETS = {
  tag_name: "v0.3.0",
  html_url: "https://example/r",
  body: "notes",
  assets: [
    { name: "Speak.EPUB_0.3.0_x64-setup.exe", size: 10, browser_download_url: "https://example/setup.exe" },
    { name: "Speak-EPUB-v0.3.0-x64-portable.zip", size: 1234, browser_download_url: "https://example/portable.zip" },
  ],
};

const INFO: UpdateInfo = {
  current: "0.2.0",
  latest: "0.3.0",
  url: "https://example/r",
  notes: "",
  available: true,
  zipUrl: "https://example/portable.zip",
  zipSize: 20,
};

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
  it("returns info with portable zip asset when latest is newer", async () => {
    const fetchFn = mockFetch(RELEASE_WITH_ASSETS);
    const info = await checkForUpdates("0.2.0", fetchFn);
    expect(info?.available).toBe(true);
    expect(info?.latest).toBe("0.3.0");
    expect(info?.url).toBe("https://example/r");
    expect(info?.zipUrl).toBe("https://example/portable.zip");
    expect(info?.zipSize).toBe(1234);
  });

  it("falls back to any zip asset when no portable pattern matches", async () => {
    const fetchFn = mockFetch({
      tag_name: "v0.3.0",
      html_url: "https://example/r",
      assets: [{ name: "bundle.zip", size: 5, browser_download_url: "https://example/bundle.zip" }],
    });
    const info = await checkForUpdates("0.2.0", fetchFn);
    expect(info?.zipUrl).toBe("https://example/bundle.zip");
  });

  it("exposes empty zipUrl when release has no zip asset", async () => {
    const fetchFn = mockFetch({
      tag_name: "v0.3.0",
      html_url: "https://example/r",
      assets: [{ name: "readme.txt", size: 1, browser_download_url: "https://example/readme.txt" }],
    });
    const info = await checkForUpdates("0.2.0", fetchFn);
    expect(info?.zipUrl).toBe("");
    expect(info?.zipSize).toBe(0);
  });

  it("returns null when up to date", async () => {
    const fetchFn = mockFetch({ tag_name: "v0.2.0", html_url: "https://example/r" });
    expect(await checkForUpdates("0.2.0", fetchFn)).toBeNull();
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

describe("update prefs (store-backed)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("getUpdatePrefs defaults to auto-on and no skip on store failure", async () => {
    mockedGetStore.mockRejectedValue(new Error("no sidecar"));
    expect(await getUpdatePrefs()).toEqual({ auto: true, skipped: "" });
  });

  it("getUpdatePrefs reads updateAuto/updateSkipped and normalizes the tag", async () => {
    mockedGetStore.mockResolvedValue({ id: "1", result: { updateAuto: false, updateSkipped: "v0.3.0" } });
    expect(await getUpdatePrefs()).toEqual({ auto: false, skipped: "0.3.0" });
  });

  it("skipVersion persists the normalized tag (best effort)", async () => {
    mockedSetStore.mockResolvedValue({ id: "2", result: null });
    await skipVersion("v0.3.0");
    expect(mockedSetStore).toHaveBeenCalledWith({ updateSkipped: "0.3.0" });
    mockedSetStore.mockRejectedValue(new Error("boom"));
    await expect(skipVersion("0.3.0")).resolves.toBeUndefined();
  });
});

describe("update found event bus", () => {
  it("notifies subscribers, survives listener errors, unsubscribes", () => {
    const bad = vi.fn(() => {
      throw new Error("listener boom");
    });
    const fn = vi.fn();
    const unsubBad = onUpdateFound(bad);
    const unsub = onUpdateFound(fn);
    expect(() => announceUpdateFound(INFO)).not.toThrow();
    expect(fn).toHaveBeenCalledWith(INFO);
    unsub();
    unsubBad();
    announceUpdateFound(INFO);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("canInstallUpdates is enabled in test mode", () => {
    expect(canInstallUpdates()).toBe(true);
  });
});

describe("downloadUpdate", () => {
  type ProgressEvent = { payload: { received: number; total: number } };

  beforeEach(() => {
    vi.clearAllMocks();
    mockedInvoke.mockResolvedValue(undefined as never);
    mockedListen.mockResolvedValue(() => {});
  });

  it("asks Rust to download and forwards progress events", async () => {
    let progressCb: ((e: ProgressEvent) => void) | undefined;
    const unlisten = vi.fn();
    mockedListen.mockImplementation(async (_event, cb) => {
      progressCb = cb as (e: ProgressEvent) => void;
      return unlisten;
    });
    mockedInvoke.mockImplementation(async (cmd: string) => {
      if (cmd === "update_download_asset") {
        progressCb?.({ payload: { received: 4, total: 10 } });
        progressCb?.({ payload: { received: 10, total: 10 } });
        return 10 as never;
      }
      return undefined as never;
    });
    const onProgress = vi.fn();
    const res = await downloadUpdate(INFO, { onProgress });
    expect(res.bytes).toBe(10);
    expect(mockedListen).toHaveBeenCalledWith("updateDownloadProgress", expect.any(Function));
    expect(mockedInvoke).toHaveBeenCalledWith("update_download_asset", {
      url: INFO.zipUrl,
      tag: "0.3.0",
    });
    expect(onProgress).toHaveBeenNthCalledWith(1, { received: 4, total: 10 });
    expect(onProgress).toHaveBeenLastCalledWith({ received: 10, total: 10 });
    expect(unlisten).toHaveBeenCalled();
    const discardCalls = mockedInvoke.mock.calls.filter(([cmd]) => cmd === "update_discard");
    expect(discardCalls).toHaveLength(0);
  });

  it("normalizes Rust errors and discards the temp file", async () => {
    mockedInvoke.mockImplementation(async (cmd: string) => {
      if (cmd === "update_download_asset") throw "HTTP 500";
      return undefined as never;
    });
    await expect(downloadUpdate(INFO)).rejects.toThrow("HTTP 500");
    expect(mockedInvoke).toHaveBeenCalledWith("update_discard");
  });

  it("aborting discards the download and rejects with AbortError", async () => {
    let rejectAsset: ((e: unknown) => void) | undefined;
    mockedInvoke.mockImplementation((cmd: string) => {
      if (cmd === "update_download_asset") {
        return new Promise((_res, rej) => {
          rejectAsset = rej;
        }) as never;
      }
      if (cmd === "update_discard") rejectAsset?.("cancelled");
      return Promise.resolve(undefined) as never;
    });
    const ac = new AbortController();
    const p = downloadUpdate(INFO, { signal: ac.signal });
    await vi.waitFor(() => {
      expect(mockedInvoke).toHaveBeenCalledWith("update_download_asset", expect.anything());
    });
    ac.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
    expect(mockedInvoke).toHaveBeenCalledWith("update_discard");
  });

  it("throws without touching Rust when the release has no package", async () => {
    await expect(downloadUpdate({ ...INFO, zipUrl: "" })).rejects.toThrow("no portable package");
    expect(mockedInvoke).not.toHaveBeenCalled();
    expect(mockedListen).not.toHaveBeenCalled();
  });
});
