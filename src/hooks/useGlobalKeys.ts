import { useEffect, useRef } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";

const TEXT_FIELD_TYPES = new Set(["text", "search", "number", "url", "tel", "password"]);

/** Clear a React-controlled or plain text field (native setter + input event). */
function clearField(field: HTMLInputElement | HTMLTextAreaElement): void {
  const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
  if (descriptor?.set) {
    descriptor.set.call(field, "");
  } else {
    field.value = "";
  }
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

async function closeApp(): Promise<void> {
  try {
    await getCurrentWindow().close();
  } catch {
    // Not running inside Tauri (browser dev / jsdom): best effort.
    try {
      window.close();
    } catch {
      // noop
    }
  }
}

/**
 * App-wide keyboard shortcuts (step 1: keyboard-first navigation).
 *
 * - `Delete` — clears the focused text/number field (Del = "delete text in
 *   highlighted text field"). Ignored for disabled/read-only/empty fields and
 *   outside text fields (rows, buttons, checkboxes keep their own keys).
 * - `Escape` — closes the topmost open dialog first (Preview → Filters →
 *   Settings via `closeTopModal`), otherwise closes the app window.
 *   Focus inside the chapter grid is exempt (row handler stops propagation)
 *   so Esc never nukes list navigation by accident.
 *
 * Arrows/Tab/Enter keep working where they already do: roving tabindex +
 * arrows/Enter/Space in both tables, Enter confirms the range bar, Tab follows
 * native order (input → clear → paste → result row → …).
 */
export function useGlobalKeys(closeTopModal: () => boolean): void {
  const closerRef = useRef(closeTopModal);
  closerRef.current = closeTopModal;

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        if (e.defaultPrevented) return;
        if (closerRef.current()) return;
        void closeApp();
      } else if (e.key === "Delete") {
        const target = e.target as HTMLElement | null;
        if (!target) return;
        const tag = target.tagName;
        const isTextField =
          tag === "TEXTAREA" ||
          (tag === "INPUT" && TEXT_FIELD_TYPES.has((target as HTMLInputElement).type));
        if (!isTextField) return;
        const field = target as HTMLInputElement | HTMLTextAreaElement;
        if (field.disabled || field.readOnly || !field.value) return;
        e.preventDefault();
        clearField(field);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);
}
