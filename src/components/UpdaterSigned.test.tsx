import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockCheck = vi.fn();

vi.mock("@tauri-apps/plugin-updater", () => ({
  check: (...a: unknown[]) => mockCheck(...a),
}));

vi.mock("@/lib/sidecar", () => ({
  getStore: vi.fn().mockResolvedValue({ id: "1", result: { updateAuto: true, updateSkipped: "" } }),
  setStore: vi.fn().mockResolvedValue({ id: "1", result: {} }),
}));

const mockInstallSignedUpdate = vi.fn().mockResolvedValue({ bytes: 10 });
const mockDownloadUpdate = vi.fn();
const mockApplyUpdate = vi.fn();
const mockOpenReleaseUrl = vi.fn();

vi.mock("@/lib/updater", async () => {
  const actual = await vi.importActual<typeof import("@/lib/updater")>("@/lib/updater");
  return {
    ...actual,
    getCurrentVersion: vi.fn().mockResolvedValue("0.3.12"),
    getUpdatePrefs: vi.fn().mockResolvedValue({ auto: true, skipped: "" }),
    installSignedUpdate: (...a: unknown[]) => mockInstallSignedUpdate(...a),
    downloadUpdate: (...a: unknown[]) => mockDownloadUpdate(...a),
    applyUpdate: (...a: unknown[]) => mockApplyUpdate(...a),
    openReleaseUrl: (...a: unknown[]) => mockOpenReleaseUrl(...a),
    onUpdateFound: vi.fn(() => () => {}),
  };
});

import UpdaterBanner from "@/components/UpdaterBanner";
import { invoke } from "@tauri-apps/api/core";

describe("UpdaterBanner — signed updates", () => {
  beforeEach(() => {
    mockCheck.mockReset();
    mockInstallSignedUpdate.mockClear();
    mockDownloadUpdate.mockClear();
    vi.mocked(invoke).mockImplementation(async (cmd: string) => {
      if (cmd === "update_install_kind") return "nsis";
      if (cmd === "app_log_line") return null;
      return null;
    });
  });

  it("offers the update found in the signed manifest", async () => {
    mockCheck.mockResolvedValue({
      version: "9.9.9",
      currentVersion: "0.3.12",
      body: "signed manifest notes",
      length: 4242,
      downloadAndInstall: vi.fn(),
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    expect(screen.getByTestId("updater-text").textContent).toContain("0.3.12");
    expect(screen.getByTestId("updater-text").textContent).toContain("9.9.9");
  });

  it("installs a signed update in place on an NSIS installation", async () => {
    const downloadAndInstall = vi.fn().mockResolvedValue(undefined);
    mockCheck.mockResolvedValue({
      version: "9.9.9",
      currentVersion: "0.3.12",
      body: "",
      length: 4242,
      downloadAndInstall,
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    screen.getByTestId("updater-install").click();
    await waitFor(() => {
      expect(mockInstallSignedUpdate).toHaveBeenCalled();
    });
    expect(mockDownloadUpdate).not.toHaveBeenCalled();
  });

  it("sends a portable build to the release page", async () => {
    mockCheck.mockResolvedValue({
      version: "9.9.9",
      currentVersion: "0.3.12",
      body: "",
      length: 4242,
      downloadAndInstall: vi.fn(),
    });
    vi.mocked(invoke).mockImplementation(async (cmd: string) => {
      if (cmd === "update_install_kind") return "portable";
      if (cmd === "app_log_line") return null;
      return null;
    });
    render(<UpdaterBanner />);
    await waitFor(() => {
      expect(screen.getByTestId("updater-banner")).toBeInTheDocument();
    });
    screen.getByTestId("updater-install").click();
    await waitFor(() => {
      expect(mockOpenReleaseUrl).toHaveBeenCalled();
    });
    expect(mockInstallSignedUpdate).not.toHaveBeenCalled();
  });
});
