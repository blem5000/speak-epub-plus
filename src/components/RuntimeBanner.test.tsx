import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

const listenMock = vi.fn();

vi.mock("@tauri-apps/api/event", () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

import RuntimeBanner from "@/components/RuntimeBanner";

describe("RuntimeBanner", () => {
  beforeEach(() => {
    listenMock.mockReset();
    listenMock.mockResolvedValue(() => undefined);
  });

  it("shows nothing when no runtime download is running", async () => {
    render(<RuntimeBanner />);
    await waitFor(() => expect(listenMock).toHaveBeenCalled());
    expect(screen.queryByTestId("runtime-banner")).toBeNull();
  });

  it("shows the download progress", async () => {
    let progressCb: ((e: { payload: { received: number; total: number } }) => void) | null = null;
    let readyCb: (() => void) | null = null;
    listenMock.mockImplementation((event: string, cb: (e: never) => void) => {
      if (event === "runtimeDownloadProgress") progressCb = cb as never;
      if (event === "runtimeReady") readyCb = cb as never;
      return Promise.resolve(() => undefined);
    });
    render(<RuntimeBanner />);
    await waitFor(() => expect(progressCb).toBeTruthy());
    act(() => {
      progressCb?.({ payload: { received: 25, total: 100 } });
    });
    const banner = await screen.findByTestId("runtime-banner");
    expect(banner.textContent).toContain("25");
    expect(screen.getByTestId("runtime-progress")).toBeTruthy();
    // the runtime is ready -> the banner disappears
    act(() => {
      readyCb?.();
    });
    await waitFor(() => expect(screen.queryByTestId("runtime-banner")).toBeNull());
  });
});
