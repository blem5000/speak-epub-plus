import { useCallback, useEffect, useRef, useState } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { t } from "@/i18n";
import {
  getStore,
  setStore,
  listVoices,
  localVoices,
  kokoroVoices,
  downloadLocalVoice,
  downloadKokoroModel,
  previewVoice,
} from "@/lib/sidecar";

/**
 * Compact engine + voice picker for the wizard row.
 *
 * The full Settings form stays the place for catalogues and tuning; this is
 * the shortcut a user needs before pressing Start: which engine, which voice,
 * and is that voice actually available. The rule is deliberately blunt —
 * a voice that is not downloaded offers "download", a downloaded one offers
 * "listen". Nothing is downloaded as a side effect of picking it.
 */

type Engine = "auto" | "edge" | "local" | "kokoro";

type VoiceOption = {
  id: string;
  label: string;
  downloaded: boolean;
};

const ENGINES: Engine[] = ["auto", "edge", "local", "kokoro"];

export default function VoicePicker(): JSX.Element {
  const [engine, setEngine] = useState<Engine>("auto");
  const [edgeVoice, setEdgeVoice] = useState<string>("en-US-AndrewNeural");
  const [piperVoice, setPiperVoice] = useState<string>("");
  const [kokoroVoice, setKokoroVoice] = useState<string>("am_michael");
  const [rate, setRate] = useState<string>("+0%");

  const [edgeOptions, setEdgeOptions] = useState<VoiceOption[]>([]);
  const [piperOptions, setPiperOptions] = useState<VoiceOption[]>([]);
  const [kokoroOptions, setKokoroOptions] = useState<VoiceOption[]>([]);
  const [kokoroModelReady, setKokoroModelReady] = useState<boolean>(false);
  const [defaultPiper, setDefaultPiper] = useState<string>("en_US-lessac-medium");
  const [defaultKokoro, setDefaultKokoro] = useState<string>("am_michael");

  const [busy, setBusy] = useState<boolean>(false);
  const [msg, setMsg] = useState<string>("");
  const [playing, setPlaying] = useState<boolean>(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const selectedPiper = piperVoice || defaultPiper;
  const selectedKokoro = kokoroVoice || defaultKokoro;

  /** Mirror of the backend's auto resolution, so the listed voice is the one
   *  that will actually speak. The backend checks the SELECTED voice, not
   *  "any downloaded voice", so this does too. */
  const effective: Exclude<Engine, "auto"> =
    engine === "auto"
      ? kokoroModelReady && kokoroOptions.some((v) => v.id === selectedKokoro && v.downloaded)
        ? "kokoro"
        : piperOptions.some((v) => v.id === selectedPiper && v.downloaded)
          ? "local"
          : "edge"
      : engine;

  const load = useCallback(async (): Promise<void> => {
    try {
      const storeRes = await getStore();
      const s = (storeRes.result as Record<string, unknown>) ?? {};
      const e = String(s.engine ?? "auto").trim().toLowerCase();
      setEngine((ENGINES as string[]).includes(e) ? (e as Engine) : "auto");
      if (typeof s.voice === "string" && s.voice.trim()) setEdgeVoice(s.voice.trim());
      if (typeof s.localVoice === "string") setPiperVoice(s.localVoice.trim());
      if (typeof s.kokoroVoice === "string" && s.kokoroVoice.trim()) setKokoroVoice(s.kokoroVoice.trim());
      if (typeof s.rate === "string" && s.rate.trim()) setRate(s.rate.trim());
    } catch {
      // keep defaults
    }

    try {
      const res = await localVoices();
      const r = (res.result as Record<string, unknown>) ?? {};
      const arr = Array.isArray(r.voices) ? (r.voices as Array<Record<string, unknown>>) : [];
      setPiperOptions(
        arr.map((v) => ({
          id: String(v.id ?? ""),
          label: String(v.id ?? ""),
          downloaded: Boolean(v.downloaded),
        }))
      );
      if (typeof r.default === "string" && r.default.trim()) setDefaultPiper(r.default.trim());
    } catch {
      setPiperOptions([]);
    }

    try {
      const res = await kokoroVoices();
      const r = (res.result as Record<string, unknown>) ?? {};
      const arr = Array.isArray(r.voices) ? (r.voices as Array<Record<string, unknown>>) : [];
      setKokoroOptions(
        arr.map((v) => ({
          id: String(v.id ?? ""),
          label: `${String(v.id ?? "")} · ${String(v.accent ?? "")}${
            v.note ? ` · ${String(v.note)}` : ""
          }`,
          downloaded: Boolean(v.downloaded),
        }))
      );
      setKokoroModelReady(r.modelReady === true);
      if (typeof r.default === "string" && r.default.trim()) setDefaultKokoro(r.default.trim());
    } catch {
      setKokoroOptions([]);
      setKokoroModelReady(false);
    }

    try {
      const res = await listVoices();
      const r = (res.result as Record<string, unknown>) ?? {};
      const arr = Array.isArray(r.voices) ? (r.voices as Array<Record<string, unknown>>) : [];
      setEdgeOptions(
        arr.map((v) => ({
          id: String(v.id ?? ""),
          label: `${String(v.id ?? "")} — ${String(v.friendlyName ?? "")}`,
          // Edge voices are cloud-side: always "available"
          downloaded: true,
        }))
      );
    } catch {
      setEdgeOptions([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const persist = (patch: Record<string, unknown>): void => {
    void setStore(patch).catch(() => {});
  };

  const handleEngine = (next: Engine): void => {
    setEngine(next);
    setMsg("");
    persist({ engine: next });
  };

  const options: VoiceOption[] =
    effective === "edge" ? edgeOptions : effective === "local" ? piperOptions : kokoroOptions;

  const currentVoice =
    effective === "edge" ? edgeVoice : effective === "local" ? piperVoice || defaultPiper : kokoroVoice || defaultKokoro;

  const currentOption =
    options.find((o) => o.id === currentVoice) ??
    (effective === "edge" ? { id: currentVoice, label: currentVoice, downloaded: true } : undefined);

  const available = currentOption?.downloaded === true;

  const handleVoice = (id: string): void => {
    setMsg("");
    if (effective === "edge") {
      setEdgeVoice(id);
      persist({ voice: id });
    } else if (effective === "local") {
      setPiperVoice(id);
      persist({ localVoice: id });
    } else {
      setKokoroVoice(id);
      persist({ kokoroVoice: id });
    }
  };

  const handleDownload = async (): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setMsg("");
    try {
      const res =
        effective === "kokoro"
          ? await downloadKokoroModel({})
          : await downloadLocalVoice(currentVoice);
      if (res.error) {
        setMsg(String((res.error as { message?: string }).message ?? res.error));
      } else {
        setMsg(t("voice.downloaded") as string);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      await load();
    }
  };

  const handlePreview = async (): Promise<void> => {
    if (busy) return;
    const el = audioRef.current;
    if (el && !el.paused) {
      el.pause();
      return;
    }
    setBusy(true);
    setMsg("");
    try {
      const res = await previewVoice({
        text: t("settings.sample.text") as string,
        voice: effective === "edge" ? currentVoice : edgeVoice,
        rate,
        engine: effective,
        localVoice: effective === "edge" ? "" : currentVoice,
      });
      if (res.error) {
        setMsg(String((res.error as { message?: string }).message ?? res.error));
        return;
      }
      const path = (res.result as { path?: unknown } | null)?.path;
      if (typeof path !== "string" || !path) {
        setMsg(t("settings.sample.error") as string);
        return;
      }
      if (el) {
        el.src = convertFileSrc(path);
        void el.play().catch(() => setMsg(t("settings.sample.error") as string));
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const modelMissing = effective === "kokoro" && !kokoroModelReady;

  return (
    <div className="rounded-md border bg-card/40 p-3" data-testid="voice-picker">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-body-sm font-medium">{t("settings.engine.label")}</span>
          <div className="flex flex-wrap gap-1" role="group" aria-label={t("settings.engine.label") as string}>
            {ENGINES.map((opt) => (
              <button
                key={opt}
                type="button"
                data-testid={`voice-picker-engine-${opt}`}
                onClick={() => handleEngine(opt)}
                aria-pressed={engine === opt}
                className={`h-9 rounded-md border px-2.5 text-body-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  engine === opt
                    ? "border-accent bg-accent/10 font-medium text-accent"
                    : "border-input bg-card text-muted-foreground hover:text-foreground"
                }`}
              >
                {t(`settings.engine.${opt}`)}
              </button>
            ))}
          </div>
        </label>

        <label className="flex min-w-[240px] flex-1 flex-col gap-1">
          <span className="text-body-sm font-medium">
            {effective === "edge"
              ? t("settings.voice.label")
              : effective === "local"
                ? t("settings.localVoice.label")
                : t("settings.kokoro.voice")}
            {engine === "auto" ? (
              <span className="ml-1 font-normal text-muted-foreground">
                ({t("voice.autoUses")} {t(`settings.engine.${effective}`)})
              </span>
            ) : null}
          </span>
          <select
            data-testid="voice-picker-voice"
            value={currentVoice}
            onChange={(e) => handleVoice(e.target.value)}
            className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {options.length === 0 ? <option value={currentVoice}>{currentVoice}</option> : null}
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {`${o.label}${o.downloaded ? "" : " — " + (t("voice.notDownloaded") as string)}`}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-end gap-2">
          {available ? (
            <button
              type="button"
              data-testid="voice-picker-preview"
              disabled={busy}
              onClick={() => void handlePreview()}
              className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
              {playing ? t("settings.sample.stop") : t("settings.sample.play")}
            </button>
          ) : (
            <button
              type="button"
              data-testid="voice-picker-download"
              disabled={busy}
              onClick={() => void handleDownload()}
              className="h-9 rounded-md border border-accent/40 bg-accent/10 px-3 text-body font-medium text-accent hover:bg-accent/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
              {busy
                ? t("voice.downloading")
                : modelMissing
                  ? t("settings.kokoro.downloadModel")
                  : t("voice.download")}
            </button>
          )}
          <audio
            ref={audioRef}
            data-testid="voice-picker-audio"
            hidden
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
          />
        </div>
      </div>
      {msg ? (
        <p role="status" aria-live="polite" data-testid="voice-picker-msg" className="mt-2 text-body-sm text-muted-foreground">
          {msg}
        </p>
      ) : null}
    </div>
  );
}
