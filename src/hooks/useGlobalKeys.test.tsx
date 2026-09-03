import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { useGlobalKeys } from "./useGlobalKeys";
import { getCurrentWindow } from "@tauri-apps/api/window";

const mockedGetWindow = vi.mocked(getCurrentWindow);

describe("useGlobalKeys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = "";
  });
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("Delete clears a focused text field via input event", () => {
    const onInput = vi.fn();
    renderHook(() => useGlobalKeys(() => false));
    const input = document.createElement("input");
    input.type = "text";
    input.value = "https://novelphoenix.com/novel/x";
    input.addEventListener("input", onInput);
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "Delete", code: "Delete" });
    expect(input.value).toBe("");
    expect(onInput).toHaveBeenCalledTimes(1);
  });

  it("Delete clears number fields but ignores checkboxes and empty fields", () => {
    const onInput = vi.fn();
    renderHook(() => useGlobalKeys(() => false));
    const num = document.createElement("input");
    num.type = "number";
    num.value = "57";
    num.addEventListener("input", onInput);
    document.body.appendChild(num);
    num.focus();
    fireEvent.keyDown(num, { key: "Delete", code: "Delete" });
    expect(num.value).toBe("");
    expect(onInput).toHaveBeenCalledTimes(1);

    const box = document.createElement("input");
    box.type = "checkbox";
    document.body.appendChild(box);
    box.focus();
    fireEvent.keyDown(box, { key: "Delete", code: "Delete" });
    expect(onInput).toHaveBeenCalledTimes(1); // no extra event

    const empty = document.createElement("input");
    empty.type = "text";
    empty.value = "";
    document.body.appendChild(empty);
    empty.focus();
    fireEvent.keyDown(empty, { key: "Delete", code: "Delete" });
    expect(onInput).toHaveBeenCalledTimes(1);
  });

  it("Escape closes topmost modal first, app otherwise", async () => {
    const closeTopModal = vi.fn(() => true);
    const { rerender } = renderHook(({ fn }) => useGlobalKeys(fn), { initialProps: { fn: closeTopModal } });
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(closeTopModal).toHaveBeenCalledTimes(1);
    expect(mockedGetWindow).not.toHaveBeenCalled();

    closeTopModal.mockReturnValue(false);
    rerender({ fn: closeTopModal });
    // allow ref update to flush
    await act(async () => {});
    fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
    expect(mockedGetWindow).toHaveBeenCalledTimes(1);
  });
});
