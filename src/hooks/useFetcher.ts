import { useCallback, useEffect, useRef, useState } from "react";
import {
  callSidecar,
  onChapterStatus,
  onLogLine,
  onPartStatus,
  onThrottleChanged,
  type ChapterStatusEvent,
  type LogLineEvent,
  type PartStatusEvent,
  type ThrottleChangedEvent,
} from "@/lib/sidecar";

export type FetcherStatus = "queued" | "fetching" | "cleaning" | "done" | "error" | "skipped";
export type FetcherThrottle = ThrottleChangedEvent | null;

export type Progress = { done: number; total: number; percent: number };

export type UseFetcherReturn = {
  fetching: boolean;
  logs: string[];
  throttle: FetcherThrottle;
  statuses: Record<number, FetcherStatus>;
  partStatuses: Record<string, PartStatusEvent>;
  progress: Progress;
  elapsedSec: number;
  badge: string | null;
  error: string | null;
  start: (params: { urls?: string[]; novelUrl?: string; from?: number | null; to?: number | null }) => Promise<void>;
  abort: () => void;
  setLogs: React.Dispatch<React.SetStateAction<string[]>>;
  setStatuses: React.Dispatch<React.SetStateAction<Record<number, FetcherStatus>>>;
  setPartStatuses: React.Dispatch<React.SetStateAction<Record<string, PartStatusEvent>>>;
  appendLogs: (lines: string[]) => void;
  setStatus: (chapter: number, status: FetcherStatus) => void;
};

export function useFetcher(): UseFetcherReturn {
  const [fetching, setFetching] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [throttle, setThrottle] = useState<FetcherThrottle>({ tier: "polite", delay: 4000 });
  const [statuses, setStatuses] = useState<Record<number, FetcherStatus>>({});
  const [partStatuses, setPartStatuses] = useState<Record<string, PartStatusEvent>>({});
  const [progress, setProgress] = useState<Progress>({ done: 0, total: 0, percent: 0 });
  const [badge, setBadge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const callIdRef = useRef(0);
  const elapsedTimerRef = useRef<number | null>(null);
  const startTimeRef = useRef<number | null>(null);

  // elapsed timer when fetching
  useEffect(() => {
    if (fetching) {
      startTimeRef.current = Date.now();
      setElapsedSec(0);
      if (elapsedTimerRef.current) window.clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = window.setInterval(() => {
        if (startTimeRef.current) {
          setElapsedSec(Math.floor((Date.now() - startTimeRef.current) / 1000));
        }
      }, 1000) as unknown as number;
    } else {
      if (elapsedTimerRef.current) {
        window.clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
    }
    return () => {
      if (elapsedTimerRef.current) {
        window.clearInterval(elapsedTimerRef.current);
        elapsedTimerRef.current = null;
      }
    };
  }, [fetching]);

  // derive progress from statuses/partStatuses
  useEffect(() => {
    if (Object.keys(partStatuses).length > 0) {
      const byChapter = new Map<number, number>();
      Object.values(partStatuses).forEach((ps) => {
        if (!byChapter.has(ps.chapter_number)) byChapter.set(ps.chapter_number, ps.part_count);
        else {
          // keep max part_count if inconsistent
          const cur = byChapter.get(ps.chapter_number)!;
          if (ps.part_count > cur) byChapter.set(ps.chapter_number, ps.part_count);
        }
      });
      const total = Array.from(byChapter.values()).reduce((a, b) => a + b, 0) || Object.keys(partStatuses).length;
      const done = Object.values(partStatuses).filter((ps) => ps.status === "done" || ps.status === "skipped").length;
      const percent = total ? Math.round((done / total) * 100) : 0;
      setProgress({ done, total, percent });
    } else {
      const total = Object.keys(statuses).length;
      const done = Object.values(statuses).filter((s) => s === "done" || s === "skipped").length;
      const percent = total ? Math.round((done / total) * 100) : 0;
      setProgress({ done, total, percent });
    }
  }, [statuses, partStatuses]);

  // Subscribe to event bus AD-6: chapterStatus/partStatus/logLine/throttleChanged — capped logs
  useEffect(() => {
    let unlistenThrottle: (() => void) | null = null;
    let unlistenLog: (() => void) | null = null;
    let unlistenChapter: (() => void) | null = null;
    let unlistenPart: (() => void) | null = null;
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
        try {
          const u4 = await onPartStatus((payload: PartStatusEvent) => {
            if (cancelled) return;
            const key = `${payload.chapter_number}-${payload.part_number}`;
            setPartStatuses((prev) => ({ ...prev, [key]: payload }));
            // also log skip for TTS resume visibility
            if (payload.status === "skipped") {
              const line = `skip Chapter ${String(payload.chapter_number).padStart(3, "0")} part ${String(payload.part_number).padStart(3, "0")}/${String(payload.part_count).padStart(3, "0")}`;
              setLogs((prev) => [...prev, line].slice(-200));
            }
          });
          unlistenPart = u4;
        } catch {
          // ignore if onPartStatus not mocked (tests)
        }
      } catch {
        // ignore in jsdom where Tauri listen mocked as resolved
      }
    })();

    return () => {
      cancelled = true;
      if (unlistenThrottle) unlistenThrottle();
      if (unlistenLog) unlistenLog();
      if (unlistenChapter) unlistenChapter();
      if (unlistenPart) unlistenPart();
    };
  }, []);

  const abort = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setFetching(false);
    // timer cleanup handled by effect watching fetching
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
      // reset partStatuses for new run? Keep but clear previous? spec says queue shows per chapter pills for 1-20 without fetch — keep done?
      // For fresh bounded range, we will keep existing but overwrite; for TTS we need new.
      // We clear partStatuses on each start for isolation
      setPartStatuses({});

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
          if (code === "LOCKED") {
            setError("LOCKED");
            setBadge("Kolejka zablokowana");
            setLogs((prev) => [...prev, "queue locked", `error LOCKED: ${msg}`].slice(-200));
            return;
          }
          setError(code);
          setLogs((prev) => [...prev, `error ${code}: ${msg}`].slice(-200));
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
          setLogs((prev) => (prev.includes(badgeMsg!) ? prev : [...prev, badgeMsg!].slice(-200)));
        } else if (skipped > 0) {
          const computed = `pominięto ${skipped}`;
          setBadge(computed);
        }

        // Mark done for fetched — cap logs, respect failed (M2: sparse-safe)
        const _failedSet = (() => {
          if (data && typeof data === "object") {
            const obj = data as Record<string, unknown>;
            if (Array.isArray(obj.failed)) return new Set((obj.failed as string[]));
          }
          return new Set<string>();
        })();
        // requested chapter indices for this run (sparse-safe: from+offset, not 1..N)
        const _requestedIdx: number[] = (() => {
          try {
            if (params.urls && Array.isArray(params.urls) && params.urls.length > 0) {
              const fromN = typeof params.from === "number" ? params.from : 1;
              return params.urls.map((_, i) => fromN + i);
            }
          } catch {
            // fall through
          }
          return [];
        })();
        const _failedIdx = new Set<number>();
        try {
          if (_failedSet.size > 0 && params.urls && Array.isArray(params.urls)) {
            const fromN = typeof params.from === "number" ? params.from : 1;
            params.urls.forEach((u, i) => {
              if (_failedSet.has(u)) _failedIdx.add(fromN + i);
            });
          }
        } catch {
          // ignore mapping errors — failed stays error via statuses event
        }
        if (fetchedCount > 0) {
          setLogs((prev) => [...prev, `fetched ${fetchedCount} chapters`].slice(-200));
          setStatuses((prev) => {
            const next = { ...prev };
            // M2: mark only requested indices done; never touch unselected chapters
            const targets = _requestedIdx.length > 0
              ? _requestedIdx
              : Array.from({ length: fetchedCount + skipped }, (_, i) => i + 1);
            for (const i of targets) {
              if (_failedIdx.has(i)) {
                next[i] = "error";
                continue;
              }
              if (next[i] === "error") continue; // keep failed as error
              if (!next[i] || next[i] === "queued" || next[i] === "fetching") {
                next[i] = "done";
              }
            }
            return next;
          });
        } else if (skipped > 0 && fetchedCount === 0) {
          setLogs((prev) => [...prev, `pominięto ${skipped}, nic do pobrania`].slice(-200));
          // mark skipped chapters as done for progress
          setStatuses((prev) => {
            const next = { ...prev };
            // if statuses empty, create done for skipped range
            if (Object.keys(next).length === 0 && skipped > 0) {
              for (let i = 1; i <= skipped; i++) next[i] = "done";
            } else {
              // mark existing queued as done
              Object.keys(next).forEach((k) => {
                const idx = Number(k);
                if (next[idx] === "queued" || next[idx] === "fetching") next[idx] = "done";
              });
            }
            return next;
          });
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
          setLogs((prev) => [...prev, `VALUE_ERROR: ${msg}`].slice(-200));
        } else if (msg.includes("LIST_FAILED") || code === "LIST_FAILED") {
          setError("LIST_FAILED");
          setLogs((prev) => [...prev, `LIST_FAILED: ${msg}`].slice(-200));
        } else {
          setError((code as string) ?? "LIST_FAILED");
          setLogs((prev) => [...prev, `error: ${msg}`].slice(-200));
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

  const appendLogs = useCallback((lines: string[]) => {
    if (lines.length === 0) return;
    setLogs((prev) => [...prev, ...lines].slice(-200));
  }, []);

  const setStatus = useCallback((chapter: number, status: FetcherStatus) => {
    setStatuses((prev) => ({ ...prev, [chapter]: status }));
  }, []);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
      if (elapsedTimerRef.current) window.clearInterval(elapsedTimerRef.current);
    };
  }, []);

  return { fetching, logs, throttle, statuses, partStatuses, progress, elapsedSec, badge, error, start, abort, setLogs, setStatuses, setPartStatuses, appendLogs, setStatus };
}
