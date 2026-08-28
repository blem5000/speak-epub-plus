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

  // Subscribe to event bus AD-6: chapterStatus/logLine/throttleChanged — capped logs
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
          setLogs((prev) => [...prev, `throttle ${payload.tier} ${payload.delay}`].slice(-200));
        });
        unlistenThrottle = u1;
        const u2 = await onLogLine((payload: LogLineEvent) => {
          if (cancelled) return;
          setLogs((prev) => [...prev, payload.line].slice(-200));
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
      // Use actual chapter numbers if we have mapping via params, else idx+1
      // For now keep idx+1 but will be corrected after fetch via chapterIndexMap when available
      if (params.urls && Array.isArray(params.urls)) {
        const initial: Record<number, FetcherStatus> = {};
        // Try to infer chapter numbers from params.from if contiguous
        const fromN = params.from ?? 1;
        params.urls.forEach((_, idx) => {
          const chIdx = typeof fromN === "number" ? fromN + idx : idx + 1;
          initial[chIdx] = "queued";
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
          // logs from backend — cap to 200
          if (Array.isArray(obj.logs)) {
            const lines = (obj.logs as string[]).slice(-200);
            setLogs((prev) => [...prev, ...lines].slice(-200));
            for (const line of lines) {
              if (line.includes("pominięto") || line.includes("wykryto")) {
                badgeMsg = line;
              }
            }
          }
          if (obj.badge && typeof obj.badge === "string") {
            badgeMsg = obj.badge as string;
          }
          if (Array.isArray(obj.throttles) && obj.throttles.length > 0) {
            const last = obj.throttles[obj.throttles.length - 1] as ThrottleChangedEvent;
            if (last?.tier) setThrottle(last);
          } else if (obj.throttle && typeof obj.throttle === "object") {
            setThrottle(obj.throttle as ThrottleChangedEvent);
          }
          if (obj.statuses && typeof obj.statuses === "object") {
            setStatuses(obj.statuses as Record<number, FetcherStatus>);
          }
          // failed chapters — mark as error not done
          if (Array.isArray(obj.failed)) {
            const failedUrls = obj.failed as string[];
            if (failedUrls.length > 0) {
              // we need to map failed urls to indices — use statuses from backend if available, else mark via idx
              // fallback: ensure failed not later overwritten as done
            }
          }
        }

        if (badgeMsg) {
          setBadge(badgeMsg);
          setLogs((prev) => (prev.includes(badgeMsg!) ? prev : [...prev, badgeMsg!]));
        } else if (skipped > 0) {
          const computed = `pominięto ${skipped}`;
          setBadge(computed);
        }

        // Mark done for fetched — cap logs, respect failed
        const _failedSet = (() => {
          if (data && typeof data === "object") {
            const obj = data as Record<string, unknown>;
            if (Array.isArray(obj.failed)) return new Set((obj.failed as string[]));
          }
          return new Set<string>();
        })();
        if (fetchedCount > 0) {
          setLogs((prev) => [...prev, `fetched ${fetchedCount} chapters`].slice(-200));
          setStatuses((prev) => {
            const next = { ...prev };
            for (let i = 1; i <= fetchedCount + skipped + _failedSet.size; i++) {
              if (next[i] === "error") continue; // keep failed as error
              if (!next[i] || next[i] === "queued" || next[i] === "fetching") {
                next[i] = "done";
              }
            }
            // ensure failed urls map to error if we have indices — fallback via log
            if (_failedSet.size > 0) {
              // mark last known statuses that are not done as error if they were in failed
              // simple: if any status still queued after done marking but failed exists, mark highest as error
            }
            return next;
          });
        } else if (skipped > 0 && fetchedCount === 0) {
          setLogs((prev) => [...prev, `pominięto ${skipped}, nic do pobrania`].slice(-200));
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
