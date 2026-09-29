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
    openReleaseUrl: vi.fn(),
  };
});

const mocked = vi.mocked(updater);

describe("UpdaterBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("shows banner when newer release exists", async () => {
    mocked.getCurrentVersion.mockResolvedValue("0.1.4");
    mocked.checkForUpdates.mockResolvedValue({
      current: "0.1.4",
      latest: "0.2.0",
      url: "https://example/release",
      notes: "",
      available: true,
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("updater-text").textContent).toMatch(/0\.2\.0/);
  });

  it("stays hidden when up to date or version unknown", async () => {
    mocked.getCurrentVersion.mockResolvedValue("0.2.0");
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

  it("download opens url, dismiss hides and persists", async () => {
    mocked.getCurrentVersion.mockResolvedValue("0.1.4");
    mocked.checkForUpdates.mockResolvedValue({
      current: "0.1.4",
      latest: "0.2.0",
      url: "https://example/release",
      notes: "",
      available: true,
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("updater-download"));
    expect(mocked.openReleaseUrl).toHaveBeenCalledWith("https://example/release");
    fireEvent.click(screen.getByTestId("updater-dismiss"));
    expect(screen.queryByTestId("updater-banner")).toBeNull();
    expect(window.localStorage.getItem("speakepub.dismissed-update")).toBe("0.2.0");
  });
});
