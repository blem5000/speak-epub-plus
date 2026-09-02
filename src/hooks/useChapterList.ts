import { useEffect, useState, useRef } from "react";
import { callSidecar } from "@/lib/sidecar";

export type ChapterInfo = {
  index: number;
  title: string;
  url: string;
  cover_url?: string | null;
};

export type UseChapterListReturn = {
  loading: boolean;
  list: ChapterInfo[];
  error: string | null;
  cover: string | null;
};

export function useChapterList(url: string | null): UseChapterListReturn {
  const [loading, setLoading] = useState(false);
  const [list, setList] = useState<ChapterInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cover, setCover] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const callIdRef = useRef(0);

  useEffect(() => {
    const trimmed = url?.trim() ?? "";
    if (!trimmed) {
      // null or empty → clear
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      setLoading(false);
      setList([]);
      setError(null);
      setCover(null);
      return;
    }

    // Validate ^https?:// without network
    if (!/^https?:\/\//i.test(trimmed)) {
      setLoading(false);
      setList([]);
      setError("VALUE_ERROR");
      setCover(null);
      return;
    }
    // P9: host guard early — only novelphoenix allowed for real listChapters
    try {
      const parsed = new URL(trimmed);
      const host = (parsed.hostname || "").toLowerCase().replace(/\.$/, "");
      const allowed = host === "novelphoenix.com" || host === "www.novelphoenix.com" || host.endsWith(".novelphoenix.com");
      if (!allowed) {
        setLoading(false);
        setList([]);
        setError("LIST_FAILED");
        setCover(null);
        return;
      }
    } catch {
      setLoading(false);
      setList([]);
      setError("VALUE_ERROR");
      setCover(null);
      return;
    }

    const id = ++callIdRef.current;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    let timeoutId: number | null = null;
    const timeoutPromise: Promise<never> =
      typeof window === "undefined"
        ? new Promise<never>(() => {}) // SSR: no timeout, never settles, fetch decides
        : new Promise<never>((_, reject) => {
            timeoutId = window.setTimeout(() => {
              controller.abort();
              reject(new Error("timeout"));
            }, 5000);
          });
    // attach catch before race to avoid unhandled rejection if fetch wins early
    timeoutPromise.catch(() => {});

    const fetchPromise = (async () => {
      const res = await callSidecar("listChapters", { url: trimmed }, { signal: controller.signal });
      // handle abort quickly
      if (controller.signal.aborted) throw Object.assign(new Error("aborted"), { code: "ABORTED" });
      if ((res as { error?: unknown }).error) {
        const err = (res as { error: { code?: string; message?: string } }).error;
        const code = err?.code ?? "LIST_FAILED";
        const msg = err?.message ?? code;
        // ABORTED maps to LIST_FAILED for UI
        if (code === "ABORTED") throw Object.assign(new Error("aborted"), { code: "ABORTED" });
        throw Object.assign(new Error(msg), { code });
      }
      const data = (res as { result?: unknown }).result;
      let arr: unknown = data;
      let coverUrl: string | null = null;
      if (data != null && typeof data === "object" && !Array.isArray(data) && "chapters" in (data as Record<string, unknown>)) {
        arr = (data as { chapters: unknown }).chapters;
        coverUrl = (data as { cover_url?: string }).cover_url ?? null;
      }
      if (!Array.isArray(arr)) arr = [];
      const normalized: ChapterInfo[] = (arr as Array<Record<string, unknown>>).map((r, idx) => {
        const indexRaw = r.index ?? r.Index ?? idx + 1;
        const rawNum = Number(indexRaw);
        const index = Number.isFinite(rawNum) ? Math.max(1, Math.trunc(rawNum)) : idx + 1;
        let title = (r.title as string) ?? (r.name as string) ?? "";
        if (typeof title !== "string" || !title.trim()) title = "—";
        const urlVal = (r.url as string) ?? (r.link as string) ?? "";
        const cu = (r.cover_url as string) ?? null;
        if (cu && !coverUrl) coverUrl = cu;
        return { index, title: String(title).trim() || "—", url: String(urlVal), cover_url: cu };
      });
      normalized.sort((a, b) => a.index - b.index);
      return { list: normalized, cover: coverUrl };
    })();

    Promise.race([fetchPromise, timeoutPromise])
      .then((result) => {
        if (id !== callIdRef.current) return;
        if (controller.signal.aborted) return;
        const { list: norm, cover: c } = result as { list: ChapterInfo[]; cover: string | null };
        setList(norm);
        setCover(c);
        setError(null);
      })
      .catch((e: unknown) => {
        if (id !== callIdRef.current) return;
        const msg = e instanceof Error ? e.message : String(e);
        const code = (e as { code?: string })?.code;
        if (code === "ABORTED" || msg === "aborted") {
          // silent cancel — rapid URL change, keep previous state, no toast
          return;
        } else if (controller.signal.aborted && msg === "timeout") {
          setList([]);
          setCover(null);
          setError("LIST_FAILED");
        } else if (code === "VALUE_ERROR" || msg.includes("VALUE_ERROR")) {
          setList([]);
          setCover(null);
          setError("VALUE_ERROR");
        } else if (code === "LIST_FAILED" || msg.includes("LIST_FAILED")) {
          setList([]);
          setCover(null);
          setError("LIST_FAILED");
        } else {
          setList([]);
          setCover(null);
          setError((code as string) ?? "LIST_FAILED");
        }
      })
      .finally(() => {
        if (id !== callIdRef.current) {
          if (timeoutId && typeof window !== "undefined") window.clearTimeout(timeoutId);
          return;
        }
        if (timeoutId && typeof window !== "undefined") window.clearTimeout(timeoutId);
        setLoading(false);
        abortRef.current = null;
      });
    // P20: prevent unhandled late rejection if fetch loses race
    fetchPromise.catch(() => {});

    return () => {
      controller.abort();
      if (timeoutId && typeof window !== "undefined") window.clearTimeout(timeoutId);
    };
  }, [url]);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  return { loading, list, error, cover };
}
