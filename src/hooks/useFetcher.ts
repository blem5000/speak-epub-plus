import { useCallback, useEffect, useRef, useState } from "react";
import {
  callSidecar,
  onChapterStatus,
  onLogLine,
  onThrottleChanged,
  type ChapterStatusEvent,
  type LogLineEvent,
  type ThrottleChangedEvent,
} from "@/lib/sidecar";

export type FetcherStatus = "queued" | "fetching" | "cleaning" | "done" | "error";
export type FetcherThrottle = ThrottleChangedEvent | null;

export type UseFetcherReturn = {
  fetching: boolean;
  logs: string[];
  throttle: FetcherThrottle;
  statuses: Record<number, FetcherStatus>;
  badge: string | null;
  error: string | null;
  start: (params: { urls?: string[]; novelUrl?: string; from?: number | null; to?: number | null }) => Promise<void>;
  abort: () => void;
};

export function useFetcher(): UseFetcherReturn {
  const [fetching, setFetching] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [throttle, setThrottle] = useState<FetcherThrottle>({ tier: "polite", delay: 4000 });
  const [statuses, setStatuses] = useState<Record<number, FetcherStatus>>({});
  const [badge, setBadge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const callIdRef = useRef(0);

  // Subscribe to event bus AD-6: chapterStatus/logLine/throttleChanged
  useEffect(() => {
    let unlistenThrottle: (() => void) | null = null;
    let unlistenLog: (() => void) | null = null;
    let unlistenChapter: (() => void) | null = null;
    let cancelled = false;

    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    (async () => {
      try {
        const u1 = await onThrottleChanged((payload: ThrottleChangedEvent) => {
          if (cancelled) return;
          setThrottle(payload);
          // also log for pane
          setLogs((prev) => [...prev, `throttle ${payload.tier} ${payload.delay}`]);
        });
        unlistenThrottle = u1;
        const u2 = await onLogLine((payload: LogLineEvent) => {
          if (cancelled) return;
          setLogs((prev) => [...prev, payload.line]);
          // detect badge patterns pominięto / wykryto
          if (payload.line.includes("pominięto") || payload.line.includes("wykryto")) {
            setBadge(payload.line);
          }
        });
        unlistenLog = u2;
        const u3 = await onChapterStatus((payload: ChapterStatusEvent) => {
          if (cancelled) return;
          setStatuses((prev) => ({ ...prev, [payload.chapter]: payload.status as FetcherStatus }));
        });
        unlistenChapter = u3;
      } catch {
        // ignore in jsdom where Tauri listen mocked as resolved
      }
    })();

    return () => {
      cancelled = true;
      if (unlistenThrottle) unlistenThrottle();
      if (unlistenLog) unlistenLog();
      if (unlistenChapter) unlistenChapter();
    };
  }, []);

  const abort = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const start = useCallback(
    async (params: { urls?: string[]; novelUrl?: string; from?: number | null; to?: number | null }) => {
      const id = ++callIdRef.current;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setFetching(true);
      setError(null);
      // reset statuses for new run but keep logs? clear badge
      setBadge(null);

      // Initialize statuses to queued for each url index if provided
      if (params.urls && Array.isArray(params.urls)) {
        const initial: Record<number, FetcherStatus> = {};
        params.urls.forEach((_, idx) => {
          // chapter numbers are 1-indexed; use idx+1 as key
          initial[idx + 1] = "queued";
        });
        setStatuses(initial);
      }

      // default polite throttle badge
      setThrottle({ tier: "polite", delay: 4000 });

      try {
        const res = await callSidecar("fetchChapters", params, { signal: controller.signal });
        if (id !== callIdRef.current) return;
        if (controller.signal.aborted) return;

        if ((res as { error?: { code?: string; message?: string } }).error) {
          const err = (res as { error: { code?: string; message?: string } }).error;
          const code = err?.code ?? "LIST_FAILED";
          const msg = err?.message ?? code;
          if (code === "ABORTED") {
            // silent cancel, no error toast
            return;
          }
          setError(code);
          setLogs((prev) => [...prev, `error ${code}: ${msg}`]);
          // set statuses to error for remaining?
          return;
        }

        const data = (res as { result?: unknown }).result;
        let skipped = 0;
        let badgeMsg: string | null = null;
        let fetchedCount = 0;

        if (Array.isArray(data)) {
          fetchedCount = data.length;
        } else if (data && typeof data === "object") {
          const obj = data as Record<string, unknown>;
          skipped = (obj.skipped as number) ?? 0;
          const chapters = (obj.chapters as unknown[]) ?? [];
          fetchedCount = chapters.length;
          badgeMsg = (obj.badge as string | null) ?? null;
          // logs from backend
          if (Array.isArray(obj.logs)) {
            const lines = obj.logs as string[];
            setLogs((prev) => [...prev, ...lines]);
            // detect badge in logs if not in badge field
            for (const line of lines) {
              if (line.includes("pominięto") || line.includes("wykryto")) {
                badgeMsg = line;
              }
            }
          }
          if (obj.badge && typeof obj.badge === "string") {
            badgeMsg = obj.badge as string;
          }
          // throttle from backend
          if (Array.isArray(obj.throttles) && obj.throttles.length > 0) {
            const last = obj.throttles[obj.throttles.length - 1] as ThrottleChangedEvent;
            if (last?.tier) setThrottle(last);
          } else if (obj.throttle && typeof obj.throttle === "object") {
            setThrottle(obj.throttle as ThrottleChangedEvent);
          }
          // statuses
          if (obj.statuses && typeof obj.statuses === "object") {
            setStatuses(obj.statuses as Record<number, FetcherStatus>);
          }
        }

        if (badgeMsg) {
          setBadge(badgeMsg);
          setLogs((prev) => (prev.includes(badgeMsg!) ? prev : [...prev, badgeMsg!]));
        } else if (skipped > 0) {
          const computed = `pominięto ${skipped}`;
          setBadge(computed);
        }

        // Mark done for fetched
        if (fetchedCount > 0) {
          setLogs((prev) => [...prev, `fetched ${fetchedCount} chapters`]);
          // update statuses to done for fetched range if not already
          setStatuses((prev) => {
            const next = { ...prev };
            // naive: mark first fetchedCount as done
            for (let i = 1; i <= fetchedCount + skipped; i++) {
              if (!next[i] || next[i] === "queued" || next[i] === "fetching") {
                // keep queued for skipped? mark skipped as done as well
                next[i] = "done";
              }
            }
            return next;
          });
        } else if (skipped > 0 && fetchedCount === 0) {
          setLogs((prev) => [...prev, `pominięto ${skipped}, nic do pobrania`]);
        }
      } catch (e: unknown) {
        if (id !== callIdRef.current) return;
        const msg = e instanceof Error ? e.message : String(e);
        const code = (e as { code?: string })?.code;
        if (code === "ABORTED" || msg === "aborted") {
          return;
        }
        if (msg.includes("VALUE_ERROR") || code === "VALUE_ERROR") {
          setError("VALUE_ERROR");
          setLogs((prev) => [...prev, `VALUE_ERROR: ${msg}`]);
        } else if (msg.includes("LIST_FAILED") || code === "LIST_FAILED") {
          setError("LIST_FAILED");
          setLogs((prev) => [...prev, `LIST_FAILED: ${msg}`]);
        } else {
          setError((code as string) ?? "LIST_FAILED");
          setLogs((prev) => [...prev, `error: ${msg}`]);
        }
      } finally {
        if (id === callIdRef.current) {
          setFetching(false);
          abortRef.current = null;
        }
      }
    },
    []
  );

  // cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  return { fetching, logs, throttle, statuses, badge, error, start, abort };
}
