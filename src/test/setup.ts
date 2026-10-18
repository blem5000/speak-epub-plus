import "@testing-library/jest-dom";

// Mock Tauri invoke to avoid errors in jsdom
import { vi } from "vitest";

// Mock @tauri-apps/api/core invoke
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue({ id: "0", result: null }),
}));

// Mock @tauri-apps/api/event
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));

// Mock notification plugin (never shows OS notifications in tests)
vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn().mockResolvedValue(true),
  requestPermission: vi.fn().mockResolvedValue("granted"),
  sendNotification: vi.fn(),
}));

// Mock @tauri-apps/api/window (useGlobalKeys: Esc closes app)
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: vi.fn(() => ({ close: vi.fn().mockResolvedValue(undefined) })),
}));
