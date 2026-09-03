import { useEffect, useRef, useState } from "react";
import { callSidecar } from "@/lib/sidecar";

export type SearchResult = {
  site: string;
  title: string;
  url: string;
  link: string;
  chapters?: number | null;
  chapter_count?: number | null;
  author?: string | null;
  cover_url?: string | null;
};

function isUrlLike(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

function truncateTitle(title: string): string {
  if (title.length > 300) return title.slice(0, 200);
  return title;
}

function guessSiteForUrl(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host === "novelphoenix.com" || host.endsWith(".novelphoenix.com")) {
      return "novelphoenix.com";
    }
    if (host) return host;
    return "—";
  } catch {
    return "—";
  }
}

function buildMockUrlResult(url: string): SearchResult {
  // A pasted chapter URL (…/novel/<slug>/chapter-57) lists the whole novel.
  const stripped = url.trim().replace(/\/chapter-\d+(?:[/?#].*)?$/i, "");
  const trimmed = stripped || url.trim();
  const site = guessSiteForUrl(trimmed);
  let title = trimmed;
  try {
    const u = new URL(trimmed);
    const last = u.pathname.replace(/\/+$/, "").split("/").pop();
    if (last && last.length >= 2 && last.length < 80) {
      try {
        title = decodeURIComponent(last.replace(/-/g, " "));
      } catch {
        title = last.replace(/-/g, " ");
      }
    }
  } catch {
    // keep url as title
  }
  return {
    site,
    title,
    url: trimmed,
    link: trimmed,
    chapters: null,
    chapter_count: null,
    author: null,
    cover_url: null,
  };
}

export function useDebouncedSearch(query: string, delay = 400): {
  debouncedQuery: string;
  searching: boolean;
  results: SearchResult[];
  error: string | null;
  isUrlMode: boolean;
} {
  const [debouncedQuery, setDebouncedQuery] = useState(query);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const debounceRef = useRef<number | null>(null);
  const callIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  // debounce query
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setDebouncedQuery(query);
    }, delay);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, delay]);

  // search effect on debouncedQuery
  useEffect(() => {
    const trimmed = (debouncedQuery ?? "").trim();
    const id = ++callIdRef.current;

    // cleanup previous abort
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }

    // empty / whitespace → no network, clear results
    if (!trimmed) {
      setSearching(false);
      setResults([]);
      setError(null);
      return;
    }

    // URL mode → mock single row, no aggregator call
    if (isUrlLike(trimmed)) {
      // validate URL
      try {
        // will throw if invalid
        new URL(trimmed);
      } catch {
        setSearching(false);
        setResults([]);
        setError("invalid url");
        return;
      }
      // guess_adapter host-suffix already in buildMockUrlResult; not blocking if guess None
      const mock = buildMockUrlResult(trimmed);
      // If invalid host? already validated. Show mock even if guess None → "—"
      setSearching(false);
      setResults([mock]);
      setError(null);
      return;
    }

    // Title mode — validate truncate
    let title = trimmed;
    if (title.length > 300) {
      title = truncateTitle(title);
    }

    // Note: empty already handled; no ValueError network needed

    setSearching(true);
    setError(null);

    const controller = new AbortController();
    abortRef.current = controller;

    // callSidecar with 5s timeout via AbortController and Promise.race
    let timeoutId: number | null = null;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutId = window.setTimeout(() => {
        controller.abort();
        reject(new Error("timeout"));
      }, 5000);
    });

    const searchPromise = (async () => {
      const res = await callSidecar("search", { title });
      // sidecar returns {id, result} or {id, error}
      if ((res as { error?: unknown }).error) {
        const err = (res as { error: { message?: string } }).error;
        const msg = err?.message ?? "search failed";
        // map to toast search failed but don't crash
        throw new Error(msg);
      }
      const data = (res as { result?: unknown }).result;
      if (Array.isArray(data)) {
        return data as SearchResult[];
      }
      if (data == null) return [];
      return [];
    })();
    // prevent unhandled rejection if timeout wins first
    searchPromise.catch(() => {});

    Promise.race([searchPromise, timeoutPromise])
      .then((data) => {
        if (id !== callIdRef.current) return;
        if (controller.signal.aborted) return;
        // normalize to SearchResult shape (ensure link/chapters)
        const normalized: SearchResult[] = (data as SearchResult[]).map((r) => ({
          site: r.site ?? "—",
          title: r.title ?? "",
          url: r.url ?? r.link ?? "",
          link: r.link ?? r.url ?? "",
          chapters: r.chapters ?? r.chapter_count ?? null,
          chapter_count: r.chapter_count ?? r.chapters ?? null,
          author: r.author ?? null,
          cover_url: r.cover_url ?? null,
        }));
        setResults(normalized);
        setError(null);
      })
      .catch((e: unknown) => {
        if (id !== callIdRef.current) return;
        if (controller.signal.aborted && (e as Error).message === "timeout") {
          // timeout → [] per spec
          setResults([]);
          setError("search failed");
        } else {
          const msg = e instanceof Error ? e.message : String(e);
          // 4xx/5xx/timeout → [] toast search failed no crash
          setResults([]);
          // don't expose ValueError detail? but set error for toast
          if (msg.toLowerCase().includes("value_error") || msg.includes("ValueError")) {
            setError(msg);
          } else {
            setError("search failed");
          }
        }
      })
      .finally(() => {
        if (id !== callIdRef.current) return;
        if (controller.signal.aborted) return;
        if (timeoutId) window.clearTimeout(timeoutId);
        setSearching(false);
      });

    return () => {
      controller.abort();
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [debouncedQuery]);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  const isUrlMode = isUrlLike((debouncedQuery ?? "").trim());

  return { debouncedQuery, searching, results, error, isUrlMode };
}

export function useDebouncedValue<T>(value: T, delay = 400): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}
