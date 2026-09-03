import { useEffect, useState } from "react";
import { t } from "@/i18n";
import { buildAudio, getStore, isAudioResult, openPath, type AudioResult } from "@/lib/sidecar";
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
};

type AudioFormat = "mp3" | "m4b" | "m4a";

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const FORMAT_LABEL = {
  mp3: "audio.formatMP3",
  m4b: "audio.formatM4B",
  m4a: "audio.formatM4A",
} as const;

export default function Audiobook({
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
}: AudiobookProps): JSX.Element {
  const [format, setFormat] = useState<AudioFormat>("m4b");
  const [summary, setSummary] = useState<string>("");
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState<string[] | null>(null);
  const [result, setResult] = useState<AudioResult | null>(null);

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
          setSummary(t("audio.summary", { voice, parallel, chunk }) as string);
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

  const canBuild = canStart && !fetching && !building && urls.length > 0;

  const handleBuild = async (): Promise<void> => {
    if (!canBuild || !novelUrl) return;
    onClearParts();
    setBuilding(true);
    setError(null);
    setMissing(null);
    try {
      const res = await buildAudio({ novelUrl, from, to, title, urls, format });
      if (res.error) {
        const code = res.error.code;
        const msg = res.error.message;
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
        setResult(res.result as unknown as AudioResult);
        setError(null);
      } else {
        setError("unknown audio result");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setBuilding(false);
    }
  };

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

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="audio-build"
          onClick={() => void handleBuild()}
          disabled={!canBuild}
          className="rounded-md bg-accent px-4 py-2 text-body font-medium text-accent-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {building ? t("audio.building") : t("audio.build")}
        </button>
        {building ? <ProgressTrack done={progress.done} total={progress.total} /> : null}
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

      {!building && result ? (
        <div className="mt-4 space-y-3" data-testid="audio-result">
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
            <button
              type="button"
              data-testid="audio-open"
              onClick={() => void openPath(openTarget)}
              className="rounded-md border bg-card px-4 py-2 text-body hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {result.audiobook ? t("audio.openFile") : t("audio.openFolder")}
            </button>
          ) : null}
        </div>
      ) : null}

      {!building && !result ? (
        <p className="mt-3 text-body-sm text-muted-foreground" data-testid="audio-empty">
          {t("audio.notBuilt")}
        </p>
      ) : null}

      {error ? (
        <div role="alert" className="mt-3 text-body-sm text-destructive" data-testid="audio-error">
          {error}{" "}
          {missing && missing.length > 0 ? `— ${missing.slice(0, 3).join(", ")}` : ""}
        </div>
      ) : null}
    </section>
  );
}
