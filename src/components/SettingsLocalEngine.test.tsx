import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockGetStore = vi.fn();
const mockSetStore = vi.fn();
const mockLocalVoices = vi.fn();
const mockEnsureLocalEngine = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  getStore: (...a: unknown[]) => mockGetStore(...a),
  setStore: (...a: unknown[]) => mockSetStore(...a),
  localVoices: (...a: unknown[]) => mockLocalVoices(...a),
  ensureLocalEngine: (...a: unknown[]) => mockEnsureLocalEngine(...a),
  downloadLocalVoice: vi.fn(),
  previewVoice: vi.fn(),
  listVoices: vi.fn().mockResolvedValue({ id: "1", result: { voices: [] } }),
  getPronunciation: vi.fn().mockResolvedValue({ id: "1", result: { entries: [] } }),
  setPronunciation: vi.fn().mockResolvedValue({ id: "1", result: { entries: [] } }),
}));

import Settings from "@/components/Settings";

const defaultStore = {
  voice: "en-US-AriaNeural",
  rate: "+0%",
  engine: "auto",
  "chunk-size": 3500,
  parallel: 3,
  retries: 5,
  normalizeAudio: false,
  trimSilence: false,
  autoBoilerplate: true,
  keepEPUB: true,
  keepMP3: true,
  outputDir: "",
  dialogueVoice: "",
  localVoice: "",
  updateAuto: true,
  updateSkipped: "",
  locale: "pl",
};

describe("Settings — local engine install", () => {
  beforeEach(() => {
    mockGetStore.mockReset();
    mockSetStore.mockReset();
    mockLocalVoices.mockReset();
    mockEnsureLocalEngine.mockReset();
    mockGetStore.mockResolvedValue({ id: "1", result: { ...defaultStore } });
    mockLocalVoices.mockResolvedValue({
      id: "1",
      result: {
        modelsDir: "C:/models",
        default: "en_US-lessac-medium",
        voices: [{ id: "en_US-lessac-medium", lang: "en", quality: "medium", sizeMb: 63, downloaded: false }],
        piperAvailable: false,
      },
    });
  });

  it("offers the local engine download when the engine is missing", async () => {
    mockEnsureLocalEngine.mockResolvedValue({
      id: "1",
      result: { ok: true, downloaded: true, message: "local engine downloaded" },
    });
    render(<Settings open={true} onClose={vi.fn()} />);
    await waitFor(() => expect(mockLocalVoices).toHaveBeenCalled());
    const btn = await screen.findByTestId("settings-engine-install");
    expect(btn).toBeInTheDocument();

    await btn.click();
    await waitFor(() => expect(mockEnsureLocalEngine).toHaveBeenCalled());
  });

  it("hides the install button when the engine is present", async () => {
    mockLocalVoices.mockResolvedValue({
      id: "1",
      result: {
        modelsDir: "C:/models",
        default: "en_US-lessac-medium",
        voices: [{ id: "en_US-lessac-medium", lang: "en", quality: "medium", sizeMb: 63, downloaded: true }],
        piperAvailable: true,
      },
    });
    render(<Settings open={true} onClose={vi.fn()} />);
    await waitFor(() => expect(mockLocalVoices).toHaveBeenCalled());
    expect(screen.queryByTestId("settings-engine-install")).toBeNull();
  });
});
