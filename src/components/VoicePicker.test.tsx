import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetStore = vi.fn();
const mockSetStore = vi.fn();
const mockListVoices = vi.fn();
const mockLocalVoices = vi.fn();
const mockKokoroVoices = vi.fn();
const mockDownloadLocalVoice = vi.fn();
const mockDownloadKokoroModel = vi.fn();
const mockPreviewVoice = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  getStore: (...a: unknown[]) => mockGetStore(...a),
  setStore: (...a: unknown[]) => mockSetStore(...a),
  listVoices: (...a: unknown[]) => mockListVoices(...a),
  localVoices: (...a: unknown[]) => mockLocalVoices(...a),
  kokoroVoices: (...a: unknown[]) => mockKokoroVoices(...a),
  downloadLocalVoice: (...a: unknown[]) => mockDownloadLocalVoice(...a),
  downloadKokoroModel: (...a: unknown[]) => mockDownloadKokoroModel(...a),
  previewVoice: (...a: unknown[]) => mockPreviewVoice(...a),
}));

vi.mock("@tauri-apps/api/core", () => ({
  convertFileSrc: (p: string) => `asset://localhost/${encodeURIComponent(p)}`,
}));

import VoicePicker from "./VoicePicker";

function storeWith(patch: Record<string, unknown> = {}) {
  return Promise.resolve({
    result: {
      engine: "kokoro",
      voice: "en-US-AndrewNeural",
      localVoice: "en_US-ryan-high",
      kokoroVoice: "bm_daniel",
      rate: "+0%",
      ...patch,
    },
  });
}

/** Kokoro voices present but the model NOT downloaded. */
function kokoroNotReady() {
  return Promise.resolve({
    result: {
      modelReady: false,
      engineAvailable: true,
      default: "am_michael",
      voices: [
        { id: "am_michael", accent: "US", note: "calm", downloaded: false },
        { id: "am_puck", accent: "US", note: "bright", downloaded: false },
        { id: "bm_daniel", accent: "UK", note: "neutral", downloaded: false },
        { id: "bm_george", accent: "UK", note: "deep", downloaded: false },
      ],
    },
  });
}

function kokoroReady() {
  return Promise.resolve({
    result: {
      modelReady: true,
      engineAvailable: true,
      default: "am_michael",
      voices: [
        { id: "am_michael", accent: "US", note: "calm", downloaded: true },
        { id: "am_puck", accent: "US", note: "bright", downloaded: true },
        { id: "bm_daniel", accent: "UK", note: "neutral", downloaded: true },
        { id: "bm_george", accent: "UK", note: "deep", downloaded: true },
      ],
    },
  });
}

function piperVoices(downloaded = false) {
  return Promise.resolve({
    result: {
      default: "en_US-lessac-medium",
      piperAvailable: true,
      voices: [
        { id: "en_US-ryan-high", downloaded },
        { id: "pl_PL-gosia-medium", downloaded: false },
      ],
      catalog: [],
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom does not implement media playback; the component only needs the
  // promise to resolve so a failed play() does not mask a real assertion
  Object.defineProperty(window.HTMLMediaElement.prototype, "play", {
    configurable: true,
    writable: true,
    value: vi.fn().mockResolvedValue(undefined),
  });
  Object.defineProperty(window.HTMLMediaElement.prototype, "pause", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
  mockGetStore.mockImplementation(() => storeWith());
  mockSetStore.mockResolvedValue({ result: {} });
  mockListVoices.mockResolvedValue({
    result: { voices: [{ id: "en-US-AndrewNeural", friendlyName: "Andrew", gender: "Male", locale: "en-US" }] },
  });
  mockLocalVoices.mockImplementation(() => piperVoices());
  mockKokoroVoices.mockImplementation(() => kokoroNotReady());
  mockDownloadLocalVoice.mockResolvedValue({ result: { ok: true } });
  mockDownloadKokoroModel.mockResolvedValue({ result: { ok: true } });
  mockPreviewVoice.mockResolvedValue({ result: { path: "C:/tmp/sample.mp3", engine: "kokoro", durationMs: 1200 } });
});

describe("VoicePicker — engine row next to the audiobook checkbox", () => {
  it("offers all four engines", async () => {
    render(<VoicePicker />);
    await waitFor(() => expect(mockKokoroVoices).toHaveBeenCalled());
    for (const e of ["auto", "edge", "local", "kokoro"]) {
      expect(screen.getByTestId(`voice-picker-engine-${e}`)).toBeInTheDocument();
    }
  });

  it("restores the stored engine and voice", async () => {
    render(<VoicePicker />);
    await waitFor(() => expect(screen.getByTestId("voice-picker-engine-kokoro")).toHaveAttribute("aria-pressed", "true"));
    expect((screen.getByTestId("voice-picker-voice") as HTMLSelectElement).value).toBe("bm_daniel");
  });

  it("lists the voices of the chosen engine, not another engine's", async () => {
    render(<VoicePicker />);
    await waitFor(() => expect(mockKokoroVoices).toHaveBeenCalled());
    const select = screen.getByTestId("voice-picker-voice") as HTMLSelectElement;
    const ids = Array.from(select.options).map((o) => o.value);
    expect(ids).toContain("bm_daniel");
    // the Piper model id must never appear in the Kokoro list
    expect(ids).not.toContain("en_US-ryan-high");
  });

  it("shows DOWNLOAD when the voice is not downloaded", async () => {
    render(<VoicePicker />);
    await waitFor(() => expect(screen.getByTestId("voice-picker-download")).toBeInTheDocument());
    expect(screen.queryByTestId("voice-picker-preview")).toBeNull();
    // the Kokoro model is missing, so the button names the model download
    expect(screen.getByTestId("voice-picker-download").textContent).toMatch(/model Kokoro|Kokoro model/i);
  });

  it("shows PLAY when the voice is already downloaded", async () => {
    mockKokoroVoices.mockImplementation(() => kokoroReady());
    render(<VoicePicker />);
    await waitFor(() => expect(screen.getByTestId("voice-picker-preview")).toBeInTheDocument());
    expect(screen.queryByTestId("voice-picker-download")).toBeNull();
  });

  it("downloads the Kokoro model from the button", async () => {
    const user = userEvent.setup();
    render(<VoicePicker />);
    const btn = await screen.findByTestId("voice-picker-download");
    await user.click(btn);
    await waitFor(() => expect(mockDownloadKokoroModel).toHaveBeenCalled());
    // the download must not be a side effect of merely picking the voice
    expect(mockDownloadLocalVoice).not.toHaveBeenCalled();
  });

  it("plays a sample with the selected Kokoro voice", async () => {
    mockKokoroVoices.mockImplementation(() => kokoroReady());
    const user = userEvent.setup();
    render(<VoicePicker />);
    const btn = await screen.findByTestId("voice-picker-preview");
    await user.click(btn);
    await waitFor(() => expect(mockPreviewVoice).toHaveBeenCalled());
    const arg = mockPreviewVoice.mock.calls[0][0] as Record<string, unknown>;
    expect(arg.engine).toBe("kokoro");
    // Kokoro and Piper are separate namespaces: the Kokoro id must travel in
    // kokoroVoice. Sending it as `localVoice` made the backend validate it
    // against the PIPER catalogue ("unknown local voice 'bm_daniel'").
    expect(arg.kokoroVoice).toBe("bm_daniel");
    expect(arg.localVoice).toBe("");
    expect(arg.localVoice).not.toBe("en_US-ryan-high");
  });

  it("sends the Piper voice through localVoice and leaves kokoroVoice empty", async () => {
    mockLocalVoices.mockImplementation(() => piperVoices(true));
    mockGetStore.mockImplementation(() => storeWith({ engine: "local", localVoice: "en_US-ryan-high" }));
    const user = userEvent.setup();
    render(<VoicePicker />);
    const btn = await screen.findByTestId("voice-picker-preview");
    await user.click(btn);
    await waitFor(() => expect(mockPreviewVoice).toHaveBeenCalled());
    const arg = mockPreviewVoice.mock.calls[0][0] as Record<string, unknown>;
    expect(arg.engine).toBe("local");
    expect(arg.localVoice).toBe("en_US-ryan-high");
    expect(arg.kokoroVoice).toBe("");
  });

  it("switching the engine persists it and swaps the voice list", async () => {
    mockLocalVoices.mockImplementation(() => piperVoices(true));
    const user = userEvent.setup();
    render(<VoicePicker />);
    await waitFor(() => expect(mockKokoroVoices).toHaveBeenCalled());
    await user.click(screen.getByTestId("voice-picker-engine-local"));
    await waitFor(() => expect(mockSetStore).toHaveBeenCalledWith({ engine: "local" }));
    const select = screen.getByTestId("voice-picker-voice") as HTMLSelectElement;
    const ids = Array.from(select.options).map((o) => o.value);
    expect(ids).toContain("en_US-ryan-high");
    expect(ids).not.toContain("bm_daniel");
  });

  it("a downloaded Piper voice offers PLAY, not DOWNLOAD", async () => {
    mockLocalVoices.mockImplementation(() => piperVoices(true));
    mockGetStore.mockImplementation(() => storeWith({ engine: "local", localVoice: "en_US-ryan-high" }));
    render(<VoicePicker />);
    await waitFor(() => expect(screen.getByTestId("voice-picker-preview")).toBeInTheDocument());
    expect(screen.queryByTestId("voice-picker-download")).toBeNull();
  });

  it("auto names the engine it will actually use", async () => {
    mockKokoroVoices.mockImplementation(() => kokoroReady());
    mockGetStore.mockImplementation(() => storeWith({ engine: "auto", kokoroVoice: "am_puck" }));
    render(<VoicePicker />);
    await waitFor(() => expect(screen.getByTestId("voice-picker-voice")).toBeInTheDocument());
    expect(screen.getByTestId("voice-picker-voice").closest("label")?.textContent).toMatch(/użyje|uses/i);
  });
});
