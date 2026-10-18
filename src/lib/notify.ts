import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";

/**
 * OS notification for finished/failed builds. Silent when the window has
 * focus (no nagging while the user watches), permission is denied, or the
 * environment has no notification backend (jsdom/CI). Never throws.
 */
export async function notifyBuildDone(title: string, body: string): Promise<void> {
  try {
    if (typeof document !== "undefined" && document.hasFocus()) return;
    let granted = await isPermissionGranted();
    if (!granted) {
      const perm = await requestPermission();
      granted = perm === "granted";
    }
    if (!granted) return;
    sendNotification({ title, body });
  } catch {
    // notification best-effort only — never break the build flow
  }
}
