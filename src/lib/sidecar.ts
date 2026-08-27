/**
 * JSON-RPC sidecar spike — stdin/stdout primary, HTTP fallback documented.
 * GUI → Rust (tauri shell) → Python sidecar via core/config.py:get_venv_python()
 * Rust side should emit "python_sidecar_call" and spawn venv python.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type RpcRequest = {
  id: string;
  method: string;
  params?: unknown;
};

export type RpcResponse = {
  id: string;
  result?: unknown;
  error?: { code: string; message: string; retryable?: boolean };
};

/**
 * Send a typed event via Tauri emit → Python sidecar.
 * Rust handler "python_sidecar_call" should forward to sidecar stdin.
 */
export async function callSidecar(
  method: string,
  params?: unknown,
  opts?: { signal?: AbortSignal }
): Promise<RpcResponse> {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const payload: RpcRequest = { id, method, params };
  if (opts?.signal?.aborted) {
    return { id, error: { code: "ABORTED", message: "aborted" } };
  }

  // wire external abort signal if provided
  let externalAbortHandler: (() => void) | null = null;
  const linkAbort = (ctl: AbortController): void => {
    if (opts?.signal) {
      externalAbortHandler = (): void => ctl.abort();
      opts.signal.addEventListener("abort", externalAbortHandler, { once: true });
    }
  };
  const unlinkAbort = (ctl: AbortController): void => {
    if (externalAbortHandler && opts?.signal) {
      opts.signal.removeEventListener("abort", externalAbortHandler);
      externalAbortHandler = null;
    }
    void ctl;
  };

  try {
    if (opts?.signal?.aborted) throw new Error("aborted");
    // Primary: stdin/stdout via Rust shell plugin — with race against abort
    const invokePromise = invoke<RpcResponse>("python_sidecar_call", {
      payload,
    });
    if (opts?.signal) {
      const abortPromise = new Promise<never>((_, reject) => {
        opts.signal!.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
      const result = (await Promise.race([invokePromise, abortPromise])) as RpcResponse;
      return result;
    }
    const result = await invokePromise;
    return result;
  } catch (err) {
    // Fallback documented in docs/sidecar-fallback.md — keep app open, show toast
    const msg = err instanceof Error ? err.message : String(err);
    if (msg === "aborted" || opts?.signal?.aborted) {
      return { id, error: { code: "ABORTED", message: "aborted" } };
    }
    console.warn(`sidecar failed: ${msg} — falling back to http://localhost:17381`, err);
    // Attempt HTTP fallback (best-effort) with timeout and id check
    try {
      const ctl = new AbortController();
      linkAbort(ctl);
      const t = setTimeout(() => ctl.abort(), 2000);
      // if external signal already aborted, abort immediately
      if (opts?.signal?.aborted) ctl.abort();
      const res = await fetch("http://localhost:17381/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctl.signal,
      });
      clearTimeout(t);
      unlinkAbort(ctl);
      if (!res.ok) throw new Error(`http ${res.status}`);
      const json = (await res.json()) as RpcResponse;
      if (json.id !== id) throw new Error(`id mismatch ${json.id} != ${id}`);
      return json;
    } catch (httpErr) {
      const httpMsg = httpErr instanceof Error ? httpErr.message : String(httpErr);
      return {
        id,
        error: {
          code: "SIDECAR_FAILED",
          message: `sidecar failed: ${msg} fallback http also failed: ${httpMsg}`,
        },
      };
    }
  }
}

export async function ping(): Promise<boolean> {
  const res = await callSidecar("ping");
  return (res.result as { pong?: boolean })?.pong === true || res.result === "pong";
}

// Event bus types per AD-6 — single typed bus, no polling
export type ChapterStatusEvent = {
  chapter: number;
  status: "queued" | "fetching" | "cleaning" | "done" | "error";
};
export type PartStatusEvent = {
  chapter_number: number;
  part_number: number;
  part_count: number;
  is_final_chapter_file: boolean;
  status: string;
};
export type LogLineEvent = { line: string };
export type ThrottleChangedEvent = { tier: string; delay: number };

export async function onChapterStatus(
  cb: (payload: ChapterStatusEvent) => void
): Promise<UnlistenFn> {
  return listen<ChapterStatusEvent>("chapterStatus", (e) => cb(e.payload));
}
export async function onPartStatus(
  cb: (payload: PartStatusEvent) => void
): Promise<UnlistenFn> {
  return listen<PartStatusEvent>("partStatus", (e) => cb(e.payload));
}
export async function onLogLine(
  cb: (payload: LogLineEvent) => void
): Promise<UnlistenFn> {
  return listen<LogLineEvent>("logLine", (e) => cb(e.payload));
}
export async function onThrottleChanged(
  cb: (payload: ThrottleChangedEvent) => void
): Promise<UnlistenFn> {
  return listen<ThrottleChangedEvent>("throttleChanged", (e) => cb(e.payload));
}
