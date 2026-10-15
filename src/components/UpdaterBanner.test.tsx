import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import UpdaterBanner from "./UpdaterBanner";
import * as updater from "@/lib/updater";

vi.mock("@/lib/updater", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/updater")>();
  return {
    ...actual,
    getCurrentVersion: vi.fn(),
    checkForUpdates: vi.fn(),
    getUpdatePrefs: vi.fn(),
    skipVersion: vi.fn(),
    downloadUpdate: vi.fn(),
    applyUpdate: vi.fn(),
    discardUpdate: vi.fn(),
    canInstallUpdates: vi.fn(),
    openReleaseUrl: vi.fn(),
    onUpdateFound: vi.fn(() => () => {}),
  };
});

const mocked = vi.mocked(updater);

const INFO = {
  current: "0.2.0",
  latest: "0.3.0",
  url: "https://example/release",
  notes: "",
  available: true,
  zipUrl: "https://example/Speak-EPUB-v0.3.0-x64-portable.zip",
  zipSize: 1000,
};

describe("UpdaterBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getCurrentVersion.mockResolvedValue("0.2.0");
    mocked.checkForUpdates.mockResolvedValue(null);
    mocked.getUpdatePrefs.mockResolvedValue({ auto: true, skipped: "" });
    mocked.canInstallUpdates.mockReturnValue(true);
    mocked.skipVersion.mockResolvedValue(undefined);
    mocked.downloadUpdate.mockResolvedValue({ bytes: 1000 });
    mocked.applyUpdate.mockResolvedValue(undefined);
    mocked.discardUpdate.mockResolvedValue(undefined);
  });

  it("shows banner with install/skip/later when newer release exists", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("updater-text").textContent).toMatch(/0\.3\.0/);
    expect(screen.getByTestId("updater-install")).toBeInTheDocument();
    expect(screen.getByTestId("updater-skip")).toBeInTheDocument();
    expect(screen.getByTestId("updater-later")).toBeInTheDocument();
  });

  it("stays hidden when up to date or version unknown", async () => {
    mocked.checkForUpdates.mockResolvedValue(null);
    const { unmount } = render(<UpdaterBanner />);
    await waitFor(() => {
      expect(mocked.checkForUpdates).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("updater-banner")).toBeNull();
    unmount();

    mocked.getCurrentVersion.mockResolvedValue(null);
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(mocked.getCurrentVersion).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("updater-banner")).toBeNull();
  });

  it("skips the automatic check when updateAuto is off", async () => {
    mocked.getUpdatePrefs.mockResolvedValue({ auto: false, skipped: "" });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(mocked.getUpdatePrefs).toHaveBeenCalled();
    });
    expect(mocked.checkForUpdates).not.toHaveBeenCalled();
    expect(screen.queryByTestId("updater-banner")).toBeNull();
  });

  it("hides a release the user already skipped, shows a newer one", async () => {
    mocked.getUpdatePrefs.mockResolvedValue({ auto: true, skipped: "0.3.0" });
    mocked.checkForUpdates.mockResolvedValue(INFO);
    const { unmount } = render(<UpdaterBanner />);
    await waitFor(() => {
      expect(mocked.checkForUpdates).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("updater-banner")).toBeNull();
    unmount();

    mocked.getUpdatePrefs.mockResolvedValue({ auto: true, skipped: "0.2.5" });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
  });

  it("install downloads with progress then hands off to apply", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    let resolveDownload!: (v: { bytes: number }) => void;
    mocked.downloadUpdate.mockImplementation((_info, opts) => {
      opts?.onProgress?.({ received: 400, total: 1000 });
      return new Promise((res) => {
        resolveDownload = res;
      });
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-install"));
    await waitFor(() => {
      expect(screen.getByTestId("updater-progress")).toBeInTheDocument();
    });
    expect(screen.getByTestId("updater-text").textContent).toMatch(/40%/);
    resolveDownload({ bytes: 1000 });
    await waitFor(() => {
      expect(screen.getByTestId("updater-text").textContent).toMatch(/Restarting/);
    });
    expect(mocked.downloadUpdate).toHaveBeenCalledWith(
      INFO,
      expect.objectContaining({ onProgress: expect.any(Function) })
    );
    expect(mocked.applyUpdate).toHaveBeenCalledWith(INFO);
  });

  it("cancel aborts the download, discards it and restores the buttons", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    mocked.downloadUpdate.mockImplementation(
      (_info, opts) =>
        new Promise((_res, rej) => {
          opts?.signal?.addEventListener("abort", () =>
            rej(new DOMException("Aborted", "AbortError"))
          );
        })
    );
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-install"));
    await waitFor(() => {
      expect(screen.getByTestId("updater-cancel")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-cancel"));
    await waitFor(() => {
      expect(screen.getByTestId("updater-install")).toBeInTheDocument();
    });
    expect(mocked.discardUpdate).toHaveBeenCalled();
    expect(mocked.applyUpdate).not.toHaveBeenCalled();
    expect(screen.queryByTestId("updater-error")).toBeNull();
  });

  it("shows an error when the download fails", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    mocked.downloadUpdate.mockRejectedValue(new Error("HTTP 500"));
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-install"));
    await waitFor(() => {
      expect(screen.getByTestId("updater-error").textContent).toMatch(/HTTP 500/);
    });
    expect(screen.getByTestId("updater-install")).toBeInTheDocument();
  });

  it("blocks install in dev builds with a visible message", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    mocked.canInstallUpdates.mockReturnValue(false);
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-install"));
    await waitFor(() => {
      expect(screen.getByTestId("updater-error").textContent).toMatch(/development/i);
    });
    expect(mocked.downloadUpdate).not.toHaveBeenCalled();
  });

  it("falls back to the release page when the release has no zip asset", async () => {
    mocked.checkForUpdates.mockResolvedValue({ ...INFO, zipUrl: "" });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-install"));
    expect(mocked.openReleaseUrl).toHaveBeenCalledWith("https://example/release");
    expect(mocked.downloadUpdate).not.toHaveBeenCalled();
  });

  it("skip persists the version, later only hides for the session", async () => {
    mocked.checkForUpdates.mockResolvedValue(INFO);
    const { unmount } = render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-skip"));
    await waitFor(() => {
      expect(screen.queryByTestId("updater-banner")).toBeNull();
    });
    expect(mocked.skipVersion).toHaveBeenCalledWith("0.3.0");
    unmount();

    vi.clearAllMocks();
    mocked.getCurrentVersion.mockResolvedValue("0.2.0");
    mocked.getUpdatePrefs.mockResolvedValue({ auto: true, skipped: "" });
    mocked.checkForUpdates.mockResolvedValue(INFO);
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-later"));
    await waitFor(() => {
      expect(screen.queryByTestId("updater-banner")).toBeNull();
    });
    expect(mocked.skipVersion).not.toHaveBeenCalled();
  });
});
