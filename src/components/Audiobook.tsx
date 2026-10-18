import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { t } from "@/i18n";
import {
  buildAudio,
  CANCEL_METHODS_AUDIO,
  cancelSidecarJob,
  getStore,
  isAudioResult,
  onMergeProgress,
  openPath,
  revealPath,
  type AudioResult,
  type MergeProgressEvent,
} from "@/lib/sidecar";
import { notifyBuildDone } from "@/lib/notify";
import ProgressTrack from "./ProgressTrack";

type AudiobookProps = {
  novelUrl: string | null;
  from: number;
  to: number;
  title: string;
  urls: string[];
  canStart: boolean;
  fetching: boolean;
  progress: { done: number; total: number; percent: number };
  onClearParts: () => void;
  onBuildingChange?: (building: boolean) => void;
  /** Wizard mode: hide format radios + build/stop buttons (advanced panel
   *  owns the format; the wizard owns the single Start/Stop). */
  showControls?: boolean;
  /** Controlled format (advanced radios); when set, internal radios are ignored. */
  format?: AudioFormat;
  outputDir?: string;
};

/** Imperative API for the App orchestrator (single Start button). */
export type AudiobookHandle = {
  start: (formatOverride?: AudioFormat) => Promise<void>;
  stop: () => void;
};

export type AudioFormat = "mp3" | "m4b" | "m4a";

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** "65s" → "1m 05s"; "7s" → "7s". Units are intentionally locale-neutral. */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return `${m}m ${rest.toString().padStart(2, "0")}s`;
}

const FORMAT_LABEL = {
  mp3: "audio.formatMP3",
  m4b: "audio.formatM4B",
  m4a: "audio.formatM4A",
} as const;

const Audiobook = forwardRef<AudiobookHandle, AudiobookProps>(function Audiobook({
  novelUrl,
  from,
  to,
  title,
  urls,
  canStart,
  fetching,
  progress,
  onClearParts,
  onBuildingChange,
  showControls = true,
  format: formatProp,
  outputDir,
}: AudiobookProps, ref): JSX.Element {
  const [formatState, setFormatState] = useState<AudioFormat>("m4b");
  const format = formatProp ?? formatState;
  const setFormat = setFormatState;
  const [summary, setSummary] = useState<string>("");
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[] | null>(null);
  const [result, setResult] = useState<AudioResult | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const [stopped, setStopped] = useState(false);
  const startRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);
  const [merge, setMerge] = useState<MergeProgressEvent | null>(null);
  const mergeStartRef = useRef<number | null>(null);

  // Summary of TTS settings owned by Settings (voice/parallel/chunk).
  useEffect(() => {
    let alive = true;
    getStore()
      .then((res) => {
        if (!alive) return;
        const data = (res as { result?: Record<string, unknown> }).result;
        if (data && typeof data === "object") {
          const voice = typeof data.voice === "string" ? data.voice : "en-US-AndrewNeural";
          const parallel = Number(data.parallel ?? 3);
          const chunk = Number((data as Record<string, unknown>)["chunk-size"] ?? 3500);
          const bitrate = typeof data.audioBitrate === "string" ? data.audioBitrate : "32k";
          setSummary(t("audio.summary", { voice, parallel, chunk, bitrate }) as string);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    onBuildingChange?.(building);
  }, [building, onBuildingChange]);

  // Live clock for the ETA while generating (appears right after pressing Build).
  useEffect(() => {
    if (!building) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [building]);

  // Merge/multiplex phase events from the backend (per-chapter merges, M4B encode).
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | null = null;
    (async () => {
      try {
        unlisten = await onMergeProgress((payload) => {
          if (cancelled) return;
          setMerge({ ...payload });
          if (mergeStartRef.current == null) mergeStartRef.current = Date.now();
        });
      } catch {
        // ignore in jsdom where listen is mocked
      }
    })();
    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, []);

  const elapsedSec = startRef.current != null ? Math.max(0, Math.floor((now - startRef.current) / 1000)) : 0;
  const remainingSec =
    building && progress.total > 0 && progress.done > 0 && elapsedSec >= 2
      ? Math.max(0, Math.round((elapsedSec / progress.done) * (progress.total - progress.done)))
      : null;
  // Merge phase has its own clock (parts are done; chapters merge, then the
  // single-file multiplex runs indeterminately).
  const inMultiplex = building && merge?.phase === "multiplex";
  const inProbing = building && !inMultiplex && merge?.phase === "probing";
  const inMerge = building && !inMultiplex && !inProbing && merge != null && merge.total > 0;
  const mergeElapsedSec =
    mergeStartRef.current != null ? Math.max(0, Math.floor((now - mergeStartRef.current) / 1000)) : 0;
  const mergeActive = inMerge || inProbing;
  const mergeRemainingSec =
    mergeActive && merge != null && merge.done > 0 && mergeElapsedSec >= 2
      ? Math.max(0, Math.round((mergeElapsedSec / merge.done) * (merge.total - merge.done)))
      : null;
  // Multiplex carries byte-scale progress (done/total bytes); the initial
  // (0,1) heartbeat has total<=1 and stays indeterminate.
  const multiplexPct =
    inMultiplex && merge != null && merge.total > 1
      ? Math.max(0, Math.min(100, Math.round((merge.done / merge.total) * 100)))
      : null;
  const multiplexRemainingSec =
    multiplexPct !== null && merge != null && merge.done > 0 && mergeElapsedSec >= 2
      ? Math.max(0, Math.round((mergeElapsedSec / merge.done) * (merge.total - merge.done)))
      : null;

  const canBuild = canStart && !fetching && !building && urls.length > 0;

  const handleBuild = async (formatOverride?: AudioFormat): Promise<void> => {
    if (!canBuild || !novelUrl) return;
    const fmt = formatOverride ?? format;
    if (formatOverride && formatProp === undefined) setFormatState(formatOverride);
    onClearParts();
    startRef.current = Date.now();
    mergeStartRef.current = null;
    setMerge(null);
    setNow(Date.now());
    setBuilding(true);
    setStopped(false);
    setError(null);
    setMissing(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await buildAudio(
        { novelUrl, from, to, title, urls, format: fmt, outputDir: outputDir || undefined },
        { signal: controller.signal }
      );
      if (res.error) {
        const code = res.error.code;
        const msg = res.error.message;
        // User pressed Stop — detached UI, backend process killed. Not an error.
        if (code === "ABORTED" || stopRequestedRef.current) return;
        if (code === "CACHE_MISS") {
          const miss = (res.error as unknown as { missing?: string[] }).missing ?? [];
          setMissing(miss);
          setError(`${t("audio.fetchFirst")}: ${msg}`);
        } else {
          setError(`${code}: ${msg}`);
        }
        return;
      }
      if (isAudioResult(res)) {
        const done = res.result as unknown as AudioResult;
        setResult(done);
        setError(null);
        void notifyBuildDone(
          t("audio.title") as string,
          t("notify.audio.done", { n: done.chapter_count }) as string
        );
      } else {
        setError("unknown audio result");
        void notifyBuildDone(t("audio.title") as string, t("notify.audio.failed") as string);
      }
    } catch (e) {
      if (stopRequestedRef.current) return;
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      void notifyBuildDone(t("audio.title") as string, t("notify.audio.failed") as string);
    } finally {
      stopRequestedRef.current = false;
      abortRef.current = null;
      setBuilding(false);
    }
  };

  const handleStop = (): void => {
    if (!building) return;
    stopRequestedRef.current = true;
    setStopped(true);
    abortRef.current?.abort();
    abortRef.current = null;
    // Hard-stop the Python sidecar (fresh interpreter per call); without this
    // the backend would keep generating in the background after the UI aborts.
    void cancelSidecarJob([...CANCEL_METHODS_AUDIO]);
  };

  // Imperative API for the App orchestrator (wizard Start / Stop).
  useImperativeHandle(ref, () => ({
    start: (formatOverride?: AudioFormat) => handleBuild(formatOverride),
    stop: () => handleStop(),
  }));

  const openTarget = result?.audiobook?.path ?? result?.audio_dir ?? null;

  return (
    <section
      className="rounded-lg border bg-card p-6 shadow-sm"
      aria-label={t("audio.title")}
      data-testid="audiobook-section"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-heading font-semibold">{t("audio.title")}</h2>
        {building ? (
          <span className="text-body-sm text-muted-foreground" data-testid="audio-progress-label">
            {progress.total > 0 ? `${progress.done}/${progress.total}` : t("audio.building")}
          </span>
        ) : null}
      </div>

      {summary ? <p className="mt-1 text-body-sm text-muted-foreground">{summary}</p> : null}

      {showControls ? (
        <div className="mt-4 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={t("audio.format")}>
          {(["mp3", "m4b", "m4a"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={format === f}
              data-testid={`audio-format-${f}`}
              onClick={() => setFormat(f)}
              disabled={building}
              className={`rounded-md border px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ${
                format === f ? "border-accent bg-accent/15 text-foreground" : "bg-card"
              }`}
            >
              {t(FORMAT_LABEL[f])}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {showControls ? (
          <>
            <button
              type="button"
              data-testid="audio-build"
              onClick={() => void handleBuild()}
              disabled={!canBuild}
              className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {building ? t("audio.building") : t("audio.build")}
            </button>
            {building ? (
              <button
                type="button"
                data-testid="audio-stop"
                onClick={handleStop}
                className="rounded-md border border-destructive/40 bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("audio.stop")}
              </button>
            ) : null}
          </>
        ) : null}
        {building && !inMerge && !inMultiplex && !inProbing ? (
          <ProgressTrack done={progress.done} total={progress.total} />
        ) : null}
        {inMerge && merge ? <ProgressTrack done={merge.done} total={merge.total} /> : null}
        {inProbing && merge ? <ProgressTrack done={merge.done} total={merge.total} /> : null}
        {inMultiplex && merge && merge.total > 1 ? (
          <ProgressTrack done={merge.done} total={merge.total} />
        ) : null}
      </div>

      {building ? (
        <div className="mt-3 flex items-center gap-2 text-body-sm text-muted-foreground" data-testid="audio-building" role="status" aria-live="polite">
          <span
            aria-hidden="true"
            className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
          />
          {t("audio.building")}…
        </div>
      ) : null}
      {building ? (
        <div className="mt-1 text-body-sm text-muted-foreground" data-testid="audio-eta" aria-live="polite">
          {inMultiplex ? (
            <>
              {t("audio.multiplex", { format: format.toUpperCase() })}
              {multiplexPct !== null ? ` ${multiplexPct}%` : ""} ·{" "}
              {t("audio.elapsed", { elapsed: formatDuration(mergeElapsedSec) })}
              {multiplexRemainingSec !== null
                ? ` · ${t("audio.etaLeft", { remaining: formatDuration(multiplexRemainingSec) })}`
                : ""}
            </>
          ) : inProbing && merge ? (
            <>
              {t("audio.probing", { done: merge.done, total: merge.total })} ·{" "}
              {t("audio.elapsed", { elapsed: formatDuration(mergeElapsedSec) })}
              {mergeRemainingSec !== null && merge.done > 0
                ? ` · ${t("audio.etaLeft", { remaining: formatDuration(mergeRemainingSec) })}`
                : ""}
            </>
          ) : inMerge && merge ? (
            <>
              {t("audio.merging", { done: merge.done, total: merge.total })} ·{" "}
              {t("audio.elapsed", { elapsed: formatDuration(mergeElapsedSec) })}
              {mergeRemainingSec !== null
                ? ` · ${t("audio.etaLeft", { remaining: formatDuration(mergeRemainingSec) })}`
                : ""}
            </>
          ) : (
            <>
              {t("audio.elapsed", { elapsed: formatDuration(elapsedSec) })}
              {remainingSec !== null ? ` · ${t("audio.etaLeft", { remaining: formatDuration(remainingSec) })}` : ""}
            </>
          )}
        </div>
      ) : null}

      {!building && result ? (
        <div className="mt-4 space-y-3" data-testid="audio-result">
          {result.format !== "mp3" && !result.audiobook && !result.ffmpeg ? (
            <div
              role="alert"
              data-testid="audio-ffmpeg-warning"
              className="rounded-md border border-warning/20 bg-warning/10 px-3 py-2 text-body-sm text-warning-foreground"
            >
              {t("ffmpeg.missing")}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3 text-body-sm">
            <span data-testid="audio-chapters" className="rounded-full bg-muted px-3 py-1">
              {t("audio.chaptersCount", { count: result.chapter_count })}
            </span>
            <span data-testid="audio-parts" className="rounded-full bg-muted px-3 py-1">
              {t("audio.partsCount", { count: result.part_count })}
            </span>
            {result.audiobook ? (
              <span data-testid="audio-size" className="rounded-full bg-muted px-3 py-1">
                {result.audiobook.format.toUpperCase()}: {humanSize(result.audiobook.size)}
              </span>
            ) : null}
          </div>
          <div
            data-testid="audio-path"
            className="mono break-all rounded-md border bg-muted p-2 text-mono text-xs"
            style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "12px" }}
          >
            {result.audiobook?.path ?? result.audio_dir}
          </div>
          {openTarget ? (
            <div className="flex flex-wrap items-center gap-2">
              {result.audiobook ? (
                <button
                  type="button"
                  data-testid="audio-open"
                  onClick={() => {
                    openPath(openTarget).catch((e: unknown) => {
                      setToast(e instanceof Error ? e.message : String(e));
                      window.setTimeout(() => setToast(null), 4000);
                    });
                  }}
                  className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("audio.openFile")}
                </button>
              ) : null}
              <button
                type="button"
                data-testid="audio-open-folder"
                onClick={() => {
                  revealPath(result.audiobook?.path ?? result.audio_dir).catch((e: unknown) => {
                    setToast(e instanceof Error ? e.message : String(e));
                    window.setTimeout(() => setToast(null), 4000);
                  });
                }}
                className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("audio.openFolder")}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {!building && !result ? (
        <p className="mt-3 text-body-sm text-muted-foreground" data-testid="audio-empty">
          {t("audio.notBuilt")}
        </p>
      ) : null}

      {!building && stopped && !error ? (
        <div
          className="mt-3 text-body-sm text-muted-foreground"
          role="status"
          aria-live="polite"
          data-testid="audio-stopped"
        >
          {t("audio.stopped")}
        </div>
      ) : null}
      {error ? (
        <div role="alert" className="mt-3 text-body-sm text-destructive" data-testid="audio-error">
          {error}{" "}
          {missing && missing.length > 0 ? `— ${missing.slice(0, 3).join(", ")}` : ""}
        </div>
      ) : null}
      {toast ? (
        <div className="mt-2 text-body-sm text-muted-foreground" role="status" aria-live="polite" data-testid="audio-toast">
          {toast}
        </div>
      ) : null}
    </section>
  );
});

export default Audiobook;
