import { useEffect, useRef, useState } from "react";
import { t } from "@/i18n";
import { getStore, setStore, localVoices, listVoices, downloadLocalVoice, ensureLocalEngine, previewVoice } from "@/lib/sidecar";
import { convertFileSrc } from "@tauri-apps/api/core";
import { getCurrentVersion, manualCheck } from "@/lib/updater";

type SettingsProps = {
  open: boolean;
  onClose: () => void;
  /**
   * "modal" (default) — overlay dialog opened from the header gear.
   * "inline" — same form embedded in the page (Advanced panel); loads on
   * mount, no overlay, no focus trap, Esc does not close.
   */
  variant?: "modal" | "inline";
};

const VOICE_OPTIONS = [
  "en-US-AndrewNeural",
  "pl-PL-ZofiaNeural",
  "en-US-JennyNeural",
  "pl-PL-MarekNeural",
];

type EdgeVoice = {
  id: string;
  gender: string;
  locale: string;
  friendlyName: string;
};

/** The catalogue is fetched once per app run and reused between dialogs. */
let edgeVoiceCache: EdgeVoice[] | null = null;
let edgeVoiceFetch: Promise<EdgeVoice[]> | null = null;

async function fetchEdgeVoices(): Promise<EdgeVoice[]> {
  if (edgeVoiceCache) return edgeVoiceCache;
  if (!edgeVoiceFetch) {
    edgeVoiceFetch = (async () => {
      try {
        const res = await listVoices();
        const r = (res.result as Record<string, unknown>) ?? {};
        const arr = Array.isArray(r.voices) ? (r.voices as Array<Record<string, unknown>>) : [];
        const voices = arr
          .map((v) => ({
            id: String(v.id ?? ""),
            gender: String(v.gender ?? ""),
            locale: String(v.locale ?? ""),
            friendlyName: String(v.friendlyName ?? v.id ?? ""),
          }))
          .filter((v) => Boolean(v.id));
        edgeVoiceCache = voices;
        return voices;
      } catch {
        return [];
      } finally {
        edgeVoiceFetch = null;
      }
    })();
  }
  return edgeVoiceFetch;
}

const BITRATE_OPTIONS = ["32k", "48k", "64k", "96k"];

const PRESET_DELAYS = [3000, 4000, 5000] as const;

export default function Settings({ open, onClose, variant = "modal" }: SettingsProps): JSX.Element | null {
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFocusableRef = useRef<HTMLElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  // form state
  const [voice, setVoice] = useState<string>("en-US-AndrewNeural");
  const [audioBitrate, setAudioBitrate] = useState<string>("32k");
  /** The Edge catalogue — hundreds of voices, fetched once and cached in the module. */
  const [edgeVoices, setEdgeVoices] = useState<EdgeVoice[]>([]);
  const [edgeVoicesFailed, setEdgeVoicesFailed] = useState<boolean>(false);
  const [rateNum, setRateNum] = useState<number>(0);
  const [parallel, setParallel] = useState<number>(3);
  const [chunkSize, setChunkSize] = useState<number>(3500);
  const [retries, setRetries] = useState<number>(5);
  const [scrapeDelay, setScrapeDelay] = useState<number>(4000);
  const [scrapeCustom, setScrapeCustom] = useState<number>(4000);
  const [isScrapeCustom, setIsScrapeCustom] = useState(false);
  const [safeMode, setSafeMode] = useState<boolean>(false);
  const [keepEPUB, setKeepEPUB] = useState<boolean>(true);
  const [keepMP3, setKeepMP3] = useState<boolean>(true);
  const [keepM4B, setKeepM4B] = useState<boolean>(true);
  const [updateAuto, setUpdateAuto] = useState<boolean>(true);
  // "" = idle, "checking" = in flight, anything else = final message to show
  const [checkStatus, setCheckStatus] = useState<string>("");
  // local (Piper) TTS
  const [engine, setEngine] = useState<string>("auto");
  const [localVoice, setLocalVoice] = useState<string>("");
  const [localCuda, setLocalCuda] = useState<boolean>(false);
  const [localVoiceList, setLocalVoiceList] = useState<
    Array<{ id: string; lang: string; quality: string; sizeMb: number; downloaded: boolean }>
  >([]);
  /** The full upstream Piper catalogue (hundreds of voices, not only the shortlist). */
  const [localVoiceCatalog, setLocalVoiceCatalog] = useState<
    Array<{
      id: string;
      name: string;
      language: string;
      langCode: string;
      quality: string;
      sizeMb: number;
      recommended: boolean;
      downloaded: boolean;
    }>
  >([]);
  // backend-reported availability + default (release builds always bundle piper)
  const [piperAvailable, setPiperAvailable] = useState<boolean>(true);
  const [engineBusy, setEngineBusy] = useState<boolean>(false);
  const [defaultLocalVoice, setDefaultLocalVoice] = useState<string>("en_US-lessac-medium");
  const [localBusy, setLocalBusy] = useState<boolean>(false);
  const [localMsg, setLocalMsg] = useState<string>("");

  // dialogue voice (Edge only) + chapter audio post-processing
  const [dialogueVoice, setDialogueVoice] = useState<string>("");
  const [dialogueCustom, setDialogueCustom] = useState<string>("");
  const [isDialogueCustom, setIsDialogueCustom] = useState(false);
  const [normalizeAudio, setNormalizeAudio] = useState<boolean>(false);
  const [trimSilence, setTrimSilence] = useState<boolean>(false);

  // voice sample preview (Settings plays one short synthesized clip)
  const [sampleBusy, setSampleBusy] = useState<boolean>(false);
  const [samplePlaying, setSamplePlaying] = useState<boolean>(false);
  const [sampleError, setSampleError] = useState<string>("");
  const [sampleReady, setSampleReady] = useState<boolean>(false);
  const [sampleVoiceKey, setSampleVoiceKey] = useState<string>("");
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  // prev for revert
  const prevRef = useRef<Record<string, unknown>>({});

  const showToast = (msg: string): void => {
    setToast(msg);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 1500) as unknown as number;
  };

  const refreshLocalVoices = async (): Promise<void> => {
    try {
      const res = await localVoices();
      const r = (res.result as Record<string, unknown>) ?? {};
      const arr = Array.isArray(r.voices) ? (r.voices as Array<Record<string, unknown>>) : [];
      setLocalVoiceList(
        arr.map((v) => ({
          id: String(v.id ?? ""),
          lang: String(v.lang ?? ""),
          quality: String(v.quality ?? ""),
          sizeMb: Number(v.sizeMb ?? 0),
          downloaded: Boolean(v.downloaded),
        }))
      );
      const cat = Array.isArray(r.catalog) ? (r.catalog as Array<Record<string, unknown>>) : [];
      setLocalVoiceCatalog(
        cat.map((v) => ({
          id: String(v.id ?? ""),
          name: String(v.name ?? ""),
          language: String(v.language ?? ""),
          langCode: String(v.langCode ?? ""),
          quality: String(v.quality ?? ""),
          sizeMb: Number(v.sizeMb ?? 0),
          recommended: Boolean(v.recommended),
          downloaded: Boolean(v.downloaded),
        }))
      );
      setPiperAvailable(r.piperAvailable !== false);
      if (typeof r.default === "string" && r.default.trim()) setDefaultLocalVoice(r.default.trim());
    } catch {
      // surface backend failure as a failed load, not as a missing model
      setLocalMsg(t("settings.localVoice.loadError") as string);
    }
  };

  // load on open (inline variant loads on mount)
  useEffect(() => {
    if (variant !== "inline" && !open) return;
    let alive = true;
    setLoading(true);
    (async () => {      try {
        const res = await getStore();
        if (!alive) return;
        const data = (res.result as Record<string, unknown>) ?? {};
        // voice — the picker is a free-text field backed by the catalogue,
        // so any Edge short name is accepted
        const v = typeof data.voice === "string" ? (data.voice as string).trim() : "en-US-AndrewNeural";
        const voiceVal = v || "en-US-AndrewNeural";
        setVoice(voiceVal);
        prevRef.current["voice"] = voiceVal;
        // rate
        const rateStr = typeof data.rate === "string" ? (data.rate as string) : "+0%";
        const m = String(rateStr).trim().match(/^([+-]?\d+)%$/);
        let rn = 0;
        if (m) {
          try { rn = parseInt(m[1], 10); } catch { rn = 0; }
        }
        rn = Math.max(-100, Math.min(100, rn));
        setRateNum(rn);
        prevRef.current["rate"] = `${rn >= 0 ? "+" : ""}${rn}%`;
        // parallel
        let p = 3;
        try { p = parseInt(String((data.parallel as unknown) ?? 3), 10); } catch { p = 3; }
        if (!Number.isFinite(p)) p = 3;
        p = Math.max(1, Math.min(6, p));
        setParallel(p);
        prevRef.current["parallel"] = p;
        // chunk-size
        let cs = 3500;
        try {
          const cand = (data as Record<string, unknown>)["chunk-size"] as unknown;
          if (cand !== undefined) cs = parseInt(String(cand), 10);
          else if ((data as Record<string, unknown>)["chunk_size"] !== undefined) cs = parseInt(String((data as Record<string, unknown>)["chunk_size"]), 10);
        } catch { cs = 3500; }
        if (!Number.isFinite(cs)) cs = 3500;
        cs = Math.max(500, Math.min(5000, cs));
        setChunkSize(cs);
        prevRef.current["chunk-size"] = cs;
        // retries
        let rt = 5;
        try { rt = parseInt(String((data.retries as unknown) ?? 5), 10); } catch { rt = 5; }
        if (!Number.isFinite(rt)) rt = 5;
        rt = Math.max(1, Math.min(10, rt));
        setRetries(rt);
        prevRef.current["retries"] = rt;
        // scrapeDelay
        let sd = 4000;
        try {
          const raw = (data.scrapeDelay as unknown) ?? (data as Record<string, unknown>)["scrape_delay"] ?? 4000;
          sd = parseInt(String(raw), 10);
        } catch { sd = 4000; }
        if (!Number.isFinite(sd)) sd = 4000;
        sd = Math.max(0, Math.min(20000, sd));
        setScrapeDelay(sd);
        if ((PRESET_DELAYS as readonly number[]).includes(sd)) {
          setIsScrapeCustom(false);
          setScrapeCustom(sd);
        } else {
          setIsScrapeCustom(true);
          setScrapeCustom(sd);
        }
        prevRef.current["scrapeDelay"] = sd;
        // safeMode
        const sm = !!(data.safeMode ?? (data as Record<string, unknown>)["safe_mode"] ?? false);
        setSafeMode(sm);
        prevRef.current["safeMode"] = sm;
        // keeps
        setKeepEPUB(typeof data.keepEPUB === "boolean" ? (data.keepEPUB as boolean) : true);
        prevRef.current["keepEPUB"] = typeof data.keepEPUB === "boolean" ? data.keepEPUB : true;
        setKeepMP3(typeof data.keepMP3 === "boolean" ? (data.keepMP3 as boolean) : true);
        prevRef.current["keepMP3"] = typeof data.keepMP3 === "boolean" ? data.keepMP3 : true;
        setKeepM4B(typeof data.keepM4B === "boolean" ? (data.keepM4B as boolean) : true);
        prevRef.current["keepM4B"] = typeof data.keepM4B === "boolean" ? data.keepM4B : true;
        // updates
        const ua = data.updateAuto !== false;
        setUpdateAuto(ua);
        prevRef.current["updateAuto"] = ua;
        // audio bitrate
        const bv = typeof data.audioBitrate === "string" ? (data.audioBitrate as string).trim().toLowerCase() : "32k";
        const bitrateVal = BITRATE_OPTIONS.includes(bv) ? bv : "32k";
        setAudioBitrate(bitrateVal);
        prevRef.current["audioBitrate"] = bitrateVal;
        // TTS engine + local voice
        const engRaw = typeof data.engine === "string" ? (data.engine as string).trim().toLowerCase() : "auto";
        const engVal = ["auto", "edge", "local"].includes(engRaw) ? engRaw : "auto";
        setEngine(engVal);
        prevRef.current["engine"] = engVal;
        const lvVal = typeof data.localVoice === "string" ? (data.localVoice as string).trim() : "";
        setLocalVoice(lvVal);
        prevRef.current["localVoice"] = lvVal;
        const cudaVal = data.localCuda === true;
        setLocalCuda(cudaVal);
        prevRef.current["localCuda"] = cudaVal;
        // dialogue voice + post-processing flags
        const dvVal = typeof data.dialogueVoice === "string" ? (data.dialogueVoice as string).trim() : "";
        setDialogueVoice(dvVal);
        setDialogueCustom(dvVal);
        setIsDialogueCustom(Boolean(dvVal) && !VOICE_OPTIONS.includes(dvVal));
        prevRef.current["dialogueVoice"] = dvVal;
        const naVal = data.normalizeAudio === true;
        setNormalizeAudio(naVal);
        prevRef.current["normalizeAudio"] = naVal;
        const tsVal = data.trimSilence === true;
        setTrimSilence(tsVal);
        prevRef.current["trimSilence"] = tsVal;
        void refreshLocalVoices();
        setLoading(false);
      } catch {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [open, variant]);

  // the Edge voice catalogue (hundreds of voices) — fetched once, lazily
  useEffect(() => {
    if (variant !== "inline" && !open) return;
    let alive = true;
    (async () => {
      const voices = await fetchEdgeVoices();
      if (!alive) return;
      setEdgeVoices(voices);
      setEdgeVoicesFailed(voices.length === 0);
    })();
    return () => { alive = false; };
  }, [open, variant]);

  // focus trap + Esc + auto focus (modal only)
  useEffect(() => {
    if (variant === "inline" || !open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    // focus first focusable
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) {
      firstFocusableRef.current = focusable[0];
      focusable[0].focus();
    } else {
      dialog.focus();
    }
    const handleKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialog) {
        const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )).filter(el => !el.hasAttribute("disabled") && el.getAttribute("aria-hidden") !== "true");
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey) {
          if (active === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (active === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose, variant]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  const persist = async (patch: Record<string, unknown>, revertKey?: string, revertVal?: unknown): Promise<void> => {
    try {
      const res = await setStore(patch);
      if (res.error) {
        const msg = (res.error as { message?: string }).message ?? String(res.error);
        showToast(msg);
        // revert
        if (revertKey && revertVal !== undefined) {
          if (revertKey === "voice") {
            setVoice(String(revertVal));
          } else if (revertKey === "rate") {
            const ms = String(revertVal).match(/^([+-]?\d+)%$/);
            if (ms) setRateNum(parseInt(ms[1], 10));
          } else if (revertKey === "parallel") setParallel(Number(revertVal));
          else if (revertKey === "chunk-size") setChunkSize(Number(revertVal));
          else if (revertKey === "retries") setRetries(Number(revertVal));
          else if (revertKey === "scrapeDelay") {
            const rv = Number(revertVal);
            setScrapeDelay(rv);
            if ((PRESET_DELAYS as readonly number[]).includes(rv)) {
              setIsScrapeCustom(false);
              setScrapeCustom(rv);
            } else {
              setIsScrapeCustom(true);
              setScrapeCustom(rv);
            }
          } else if (revertKey === "safeMode") setSafeMode(Boolean(revertVal));
          else if (revertKey === "keepEPUB") setKeepEPUB(Boolean(revertVal));
          else if (revertKey === "keepMP3") setKeepMP3(Boolean(revertVal));
          else if (revertKey === "keepM4B") setKeepM4B(Boolean(revertVal));
          else if (revertKey === "updateAuto") setUpdateAuto(Boolean(revertVal));
          else if (revertKey === "audioBitrate") setAudioBitrate(String(revertVal));
          else if (revertKey === "engine") setEngine(String(revertVal));
          else if (revertKey === "localVoice") setLocalVoice(String(revertVal));
          else if (revertKey === "dialogueVoice") {
            const rv = String(revertVal);
            setDialogueVoice(rv);
            setDialogueCustom(rv);
            setIsDialogueCustom(Boolean(rv) && !VOICE_OPTIONS.includes(rv));
          }
          else if (revertKey === "normalizeAudio") setNormalizeAudio(Boolean(revertVal));
          else if (revertKey === "trimSilence") setTrimSilence(Boolean(revertVal));
        }
        return;
      }
      // success
      // update prevRef for reverted key
      if (revertKey) {
        const val = (patch as Record<string, unknown>)[revertKey] ?? (patch as Record<string, unknown>)[Object.keys(patch)[0]];
        prevRef.current[revertKey] = val as unknown;
      } else {
        for (const [k,v] of Object.entries(patch)) {
          prevRef.current[k] = v;
        }
      }
      const successMsg = (t("settings.toast.saved") as unknown as string) || "Zapisano";
      showToast(successMsg);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      showToast(msg);
      if (revertKey && revertVal !== undefined) {
        if (revertKey === "voice") {
          setVoice(String(revertVal));
        } else if (revertKey === "rate") { const ms = String(revertVal).match(/^([+-]?\d+)%$/); if (ms) setRateNum(parseInt(ms[1], 10)); }
        else if (revertKey === "parallel") setParallel(Number(revertVal));
        else if (revertKey === "chunk-size") setChunkSize(Number(revertVal));
        else if (revertKey === "retries") setRetries(Number(revertVal));
        else if (revertKey === "scrapeDelay") { const rv = Number(revertVal); setScrapeDelay(rv); if ((PRESET_DELAYS as readonly number[]).includes(rv)) { setIsScrapeCustom(false); setScrapeCustom(rv); } else { setIsScrapeCustom(true); setScrapeCustom(rv); } }
        else if (revertKey === "safeMode") setSafeMode(Boolean(revertVal));
        else if (revertKey === "keepEPUB") setKeepEPUB(Boolean(revertVal));
        else if (revertKey === "keepMP3") setKeepMP3(Boolean(revertVal));
        else if (revertKey === "keepM4B") setKeepM4B(Boolean(revertVal));
        else if (revertKey === "updateAuto") setUpdateAuto(Boolean(revertVal));
        else if (revertKey === "audioBitrate") setAudioBitrate(String(revertVal));
        else if (revertKey === "engine") setEngine(String(revertVal));
        else if (revertKey === "localVoice") setLocalVoice(String(revertVal));
        else if (revertKey === "dialogueVoice") {
          const rv = String(revertVal);
          setDialogueVoice(rv);
          setDialogueCustom(rv);
          setIsDialogueCustom(Boolean(rv) && !VOICE_OPTIONS.includes(rv));
        }
        else if (revertKey === "normalizeAudio") setNormalizeAudio(Boolean(revertVal));
        else if (revertKey === "trimSilence") setTrimSilence(Boolean(revertVal));
      }
    }
  };

  const handleVoiceChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    setVoice(e.target.value);
  };

  const handleVoiceBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const vv = e.target.value.trim();
    const prev = prevRef.current["voice"];
    if (!vv) {
      showToast("voice must be non-empty");
      const rv = String(prev ?? "en-US-AndrewNeural");
      setVoice(rv);
      return;
    }
    if (vv.length > 100) {
      // core will clamp, but show truncated
    }
    setVoice(vv);
    void persist({ voice: vv }, "voice", prev);
  };

  const handleBitrateChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const val = e.target.value.trim().toLowerCase();
    if (!BITRATE_OPTIONS.includes(val)) return;
    const prev = prevRef.current["audioBitrate"];
    setAudioBitrate(val);
    void persist({ audioBitrate: val }, "audioBitrate", prev);
  };

  const handleEngineChange = (val: string): void => {
    if (!["auto", "edge", "local"].includes(val) || val === engine) return;
    if (val === "local" && !piperAvailable) return; // button is disabled, belt and braces
    const prev = prevRef.current["engine"];
    setEngine(val);
    void persist({ engine: val }, "engine", prev);
  };

  const handleLocalVoiceChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    setLocalVoice(e.target.value);
    setLocalMsg("");
  };

  const handleLocalVoiceBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const val = e.target.value.trim();
    const prev = prevRef.current["localVoice"];
    setLocalVoice(val);
    void persist({ localVoice: val }, "localVoice", prev);
  };

  const handleLocalCudaChange = (checked: boolean): void => {
    const prev = prevRef.current["localCuda"];
    setLocalCuda(checked);
    void persist({ localCuda: checked }, "localCuda", prev);
  };

  const handleDialogueVoiceChange = async (e: React.ChangeEvent<HTMLSelectElement>): Promise<void> => {
    const val = e.target.value;
    if (val === "custom") {
      setIsDialogueCustom(true);
      setDialogueVoice("custom");
      setTimeout(() => {
        const el = document.querySelector<HTMLInputElement>('[data-testid="settings-audio-dialogue-custom"]');
        if (el) el.focus();
      }, 0);
      return;
    }
    const prev = prevRef.current["dialogueVoice"];
    const stored = val === "none" ? "" : val;
    setDialogueVoice(stored);
    setDialogueCustom(stored);
    setIsDialogueCustom(false);
    void persist({ dialogueVoice: stored }, "dialogueVoice", prev);
  };

  const handleDialogueCustomBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const vv = e.target.value.trim();
    const prev = prevRef.current["dialogueVoice"];
    const stored = vv;
    setDialogueCustom(vv);
    setDialogueVoice(vv);
    setIsDialogueCustom(Boolean(vv) && !VOICE_OPTIONS.includes(vv));
    void persist({ dialogueVoice: stored }, "dialogueVoice", prev);
  };

  const handleNormalizeToggle = (): void => {
    const next = !normalizeAudio;
    const prev = prevRef.current["normalizeAudio"];
    setNormalizeAudio(next);
    void persist({ normalizeAudio: next }, "normalizeAudio", prev);
  };

  const handleTrimToggle = (): void => {
    const next = !trimSilence;
    const prev = prevRef.current["trimSilence"];
    setTrimSilence(next);
    void persist({ trimSilence: next }, "trimSilence", prev);
  };

  const handlePlaySample = async (): Promise<void> => {
    if (sampleBusy) return;
    setSampleError("");
    const el = previewAudioRef.current;
    // replay/pause the cached clip — but only while voice/rate/engine are
    // unchanged; any change re-synthesizes so the sample matches the UI
    const voiceKey = `${voice}|${rateNum}|${engine}|${localVoice}`;
    if (el && sampleReady && sampleVoiceKey === voiceKey) {
      if (el.paused) {
        void el.play().catch(() => setSampleError(t("settings.sample.error") as string));
      } else {
        el.pause();
      }
      return;
    }
    setSampleBusy(true);
    try {
      // regression (v0.3.7): this call went out as previewVoice({}) — no
      // sample text, no voice/rate/engine — so the backend rejected it with
      // "text must be non-empty" and the sample never matched the UI state
      const rateStr = `${rateNum >= 0 ? "+" : ""}${rateNum}%`;
      const res = await previewVoice({
        text: t("settings.sample.text") as string,
        voice,
        rate: rateStr,
        engine,
        localVoice,
      });
      if (res.error) {
        const msg = (res.error as { message?: string }).message ?? String(res.error);
        setSampleError(msg);
        return;
      }
      const r = res.result as { path?: unknown } | null;
      const path = r && typeof r.path === "string" ? r.path : "";
      if (!path) {
        setSampleError(t("settings.sample.error") as string);
        return;
      }
      if (el) {
        el.src = convertFileSrc(path);
        setSampleReady(true);
        setSampleVoiceKey(voiceKey);
        void el.play().catch(() => setSampleError(t("settings.sample.error") as string));
      }
    } catch (e) {
      setSampleError(e instanceof Error ? e.message : String(e));
    } finally {
      setSampleBusy(false);
    }
  };

  const handleDownloadLocalVoice = async (): Promise<void> => {
    await runLocalVoiceDownload(false);
  };

  const handleRedownloadLocalVoice = async (): Promise<void> => {
    await runLocalVoiceDownload(true);
  };

  const handleEnsureLocalEngine = async (): Promise<void> => {
    if (engineBusy) return;
    setEngineBusy(true);
    setLocalMsg(t("settings.engine.installing") as string);
    try {
      const res = await ensureLocalEngine();
      if (res.error) {
        const err = res.error as { message?: string };
        const detail =
          typeof err.message === "string" && err.message ? err.message : JSON.stringify(res.error);
        setLocalMsg(`${t("settings.engine.installFailed") as string}: ${detail}`);
      } else {
        setLocalMsg(t("settings.engine.installed") as string);
        showToast(t("settings.engine.installed") as string);
        await refreshLocalVoices();
      }
    } catch (e) {
      setLocalMsg(`${t("settings.engine.installFailed") as string}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEngineBusy(false);
    }
  };

  const runLocalVoiceDownload = async (force: boolean): Promise<void> => {
    if (!piperAvailable) {
      setLocalMsg(t("settings.engine.noPiper") as string);
      return;
    }
    const target = localVoice || defaultLocalVoice;
    setLocalBusy(true);
    setLocalMsg(t("settings.localVoice.downloading") as string);
    try {
      const res = force
        ? await downloadLocalVoice(target, { force: true })
        : await downloadLocalVoice(target);
      if (res.error) {
        const err = res.error as { code?: string; message?: string };
        const code = typeof err.code === "string" ? err.code : "";
        const prefix =
          code === "DOWNLOAD_FAILED"
            ? (t("settings.localVoice.downloadFailed") as string)
            : code === "VALUE_ERROR"
              ? (t("settings.localVoice.invalidVoice") as string)
              : null;
        const detail =
          typeof err.message === "string" && err.message ? err.message : JSON.stringify(res.error);
        setLocalMsg(prefix ? `${prefix}: ${detail}` : detail);
      } else {
        setLocalMsg(t("settings.localVoice.downloaded") as string);
        showToast(t("settings.localVoice.downloaded") as string);
      }
    } catch (e) {
      setLocalMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLocalBusy(false);
      void refreshLocalVoices();
    }
  };

  const handleRateSlider = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) return;
    setRateNum(v);
  };
  const handleRateSliderBlur = (): void => {
    const prev = prevRef.current["rate"];
    const clamped = Math.max(-100, Math.min(100, rateNum));
    const rateStr = `${clamped >= 0 ? "+" : ""}${clamped}%`;
    // validate pattern
    if (!/^[+-]?\d+%$/.test(rateStr)) {
      showToast(`invalid rate pattern ${rateStr}`);
      const ms = String(prev ?? "+0%").match(/^([+-]?\d+)%$/);
      if (ms) setRateNum(parseInt(ms[1], 10));
      return;
    }
    setRateNum(clamped);
    void persist({ rate: rateStr }, "rate", prev);
  };
  const handleRateNumberChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const raw = e.target.value;
    // allow empty while typing
    if (raw === "" || raw === "-" || raw === "+") {
      // keep raw? For controlled we need parse; we can keep as string but state expects number
      // store as 0 temporarily
      return;
    }
    const v = parseInt(raw, 10);
    if (!Number.isFinite(v)) return;
    setRateNum(Math.max(-100, Math.min(100, v)));
  };
  const handleRateNumberBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const raw = e.target.value.trim();
    const prev = prevRef.current["rate"];
    // empty => revert
    if (!raw) {
      const ms = String(prev ?? "+0%").match(/^([+-]?\d+)%$/);
      if (ms) setRateNum(parseInt(ms[1], 10));
      return;
    }
    // allow raw like "-10" or "-10%" or "+10%" — normalize
    let candidate = raw;
    // if raw is like "-10" without %, add %
    if (/^[+-]?\d+$/.test(candidate)) candidate = `${candidate}%`;
    if (!/^[+-]?\d+%$/.test(candidate)) {
      showToast(`invalid rate pattern ${candidate}`);
      const ms = String(prev ?? "+0%").match(/^([+-]?\d+)%$/);
      if (ms) setRateNum(parseInt(ms[1], 10));
      return;
    }
    const num = parseInt(candidate.slice(0, -1), 10);
    const clamped = Math.max(-100, Math.min(100, num));
    const rateStr = `${clamped >= 0 ? "+" : ""}${clamped}%`;
    setRateNum(clamped);
    void persist({ rate: rateStr }, "rate", prev);
  };

  const handleParallelChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const prev = prevRef.current["parallel"];
    let v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) v = 3;
    v = Math.max(1, Math.min(6, v));
    setParallel(v);
    void persist({ parallel: v }, "parallel", prev);
  };
  const handleParallelBlur = (e: React.FocusEvent<HTMLSelectElement>): void => {
    // also handle blur for consistency
    const val = parseInt((e.target as HTMLSelectElement).value, 10);
    if (Number.isFinite(val)) {
      const clamped = Math.max(1, Math.min(6, val));
      if (clamped !== parallel) {
        const prev = prevRef.current["parallel"];
        setParallel(clamped);
        void persist({ parallel: clamped }, "parallel", prev);
      }
    }
  };

  const handleChunkBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const prev = prevRef.current["chunk-size"];
    let v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) v = 3500;
    v = Math.max(500, Math.min(5000, v));
    e.target.value = String(v);
    setChunkSize(v);
    void persist({ "chunk-size": v }, "chunk-size", prev);
  };

  const handleRetriesBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const prev = prevRef.current["retries"];
    let v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) v = 5;
    v = Math.max(1, Math.min(10, v));
    e.target.value = String(v);
    setRetries(v);
    void persist({ retries: v }, "retries", prev);
  };

  const handleScrapeDelayChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const val = e.target.value;
    if (val === "custom") {
      setIsScrapeCustom(true);
      // keep custom value as is, focus input
      setTimeout(() => {
        const el = document.querySelector<HTMLInputElement>('[data-testid="settings-scrape-custom"]');
        if (el) el.focus();
      }, 0);
      return;
    }
    const prev = prevRef.current["scrapeDelay"];
    let v = parseInt(val, 10);
    if (!Number.isFinite(v)) v = 4000;
    v = Math.max(0, Math.min(20000, v));
    setScrapeDelay(v);
    setScrapeCustom(v);
    setIsScrapeCustom(false);
    void persist({ scrapeDelay: v }, "scrapeDelay", prev);
  };

  const handleScrapeCustomBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
    const prev = prevRef.current["scrapeDelay"];
    let v = parseInt(e.target.value, 10);
    if (!Number.isFinite(v)) v = 0;
    v = Math.max(0, Math.min(20000, v));
    e.target.value = String(v);
    setScrapeCustom(v);
    setScrapeDelay(v);
    setIsScrapeCustom(true);
    void persist({ scrapeDelay: v }, "scrapeDelay", prev);
  };

  const handleSafeModeChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const prev = prevRef.current["safeMode"];
    const checked = e.target.checked;
    setSafeMode(checked);
    void persist({ safeMode: checked }, "safeMode", prev);
  };

  const handleKeepChange = (key: "keepEPUB" | "keepMP3" | "keepM4B") => (e: React.ChangeEvent<HTMLInputElement>): void => {
    const prev = prevRef.current[key];
    const checked = e.target.checked;
    if (key === "keepEPUB") setKeepEPUB(checked);
    else if (key === "keepMP3") setKeepMP3(checked);
    else setKeepM4B(checked);
    void persist({ [key]: checked }, key, prev);
  };

  const handleUpdateAutoChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    const prev = prevRef.current["updateAuto"];
    const checked = e.target.checked;
    setUpdateAuto(checked);
    void persist({ updateAuto: checked }, "updateAuto", prev);
  };

  const handleCheckNow = (): void => {
    setCheckStatus("checking");
    void (async () => {
      try {
        const info = await manualCheck();
        if (info && info.available) {
          setCheckStatus(t("settings.updates.found", { version: info.latest }));
          return;
        }
        const current = await getCurrentVersion();
        setCheckStatus(
          current
            ? t("settings.updates.latest", { version: current })
            : t("settings.updates.unavailable")
        );
      } catch {
        setCheckStatus(t("settings.updates.unavailable"));
      }
    })();
  };

  if (variant !== "inline" && !open) return null;

  const rateSliderValue = Math.max(-50, Math.min(50, rateNum));

  // the friendly description of the selected Edge voice (locale + name)
  const selectedVoice = edgeVoices.find((v) => v.id === voice);
  const selectedVoiceHint = selectedVoice
    ? `${selectedVoice.friendlyName} (${selectedVoice.locale})`
    : "";

  // the description of the selected Piper voice (language, quality, size)
  const selectedLocal = localVoiceCatalog.find((v) => v.id === localVoice);
  const selectedLocalVoiceHint = selectedLocal
    ? `${selectedLocal.language} · ${selectedLocal.quality} · ${selectedLocal.sizeMb} MB${
        selectedLocal.downloaded ? " ✓" : ""
      }`
    : "";
  const isInline = variant === "inline";

  const body = (
    <div className={isInline ? "space-y-4" : "space-y-4 p-6"}>
          {loading ? (
            <p className="text-body-sm text-muted-foreground">...</p>
          ) : (
            <>
              {/* Audio */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.audio.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.audio.title")}</h3>

                <div className="mt-4 space-y-4">
                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.audio.voice")}</span>
                    <input
                      data-testid="settings-audio-voice"
                      list="edge-voice-catalog"
                      value={voice}
                      onChange={handleVoiceChange}
                      onBlur={handleVoiceBlur}
                      placeholder="pl-PL-ZofiaNeural"
                      autoComplete="off"
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <datalist id="edge-voice-catalog">
                      {edgeVoices.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.friendlyName} · {v.locale}
                        </option>
                      ))}
                    </datalist>
                    <span className="text-body-sm text-muted-foreground" data-testid="settings-voice-hint">
                      {edgeVoicesFailed
                        ? (t("settings.voice.catalogueError") as string)
                        : edgeVoices.length
                          ? `${t("settings.voice.catalogue") as string}: ${edgeVoices.length} · ${
                              selectedVoiceHint
                            }`
                          : (t("settings.helper.voice") as string)}
                    </span>
                  </label>

                  <div className="flex items-end justify-between gap-3">
                    <button
                      type="button"
                      data-testid="settings-sample-play"
                      disabled={sampleBusy}
                      onClick={() => void handlePlaySample()}
                      className="h-9 shrink-0 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {sampleBusy
                        ? (t("settings.sample.loading") as string)
                        : samplePlaying
                          ? (t("settings.sample.stop") as string)
                          : (t("settings.sample.play") as string)}
                    </button>
                    {sampleError ? (
                      <span data-testid="settings-sample-error" className="text-body-sm text-red-600">
                        {sampleError}
                      </span>
                    ) : null}
                    <audio
                      ref={previewAudioRef}
                      data-testid="settings-sample-player"
                      hidden={true}
                      onPlay={() => setSamplePlaying(true)}
                      onPause={() => setSamplePlaying(false)}
                      onEnded={() => setSamplePlaying(false)}
                    />
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.audio.dialogue")}</span>
                    <select
                      data-testid="settings-audio-dialogue"
                      value={isDialogueCustom ? "custom" : dialogueVoice === "" ? "none" : dialogueVoice}
                      onChange={(e) => void handleDialogueVoiceChange(e)}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <option value="none">{t("settings.audio.dialogueNone")}</option>
                      {VOICE_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                      <option value="custom">{t("settings.scrape.custom")}</option>
                    </select>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.dialogue")}</span>
                  </label>
                  {isDialogueCustom ? (
                    <label className="flex flex-col gap-1">
                      <span className="text-body-sm font-medium">{t("settings.scrape.custom")}</span>
                      <input
                        data-testid="settings-audio-dialogue-custom"
                        value={dialogueCustom}
                        placeholder="pl-PL-MarekNeural"
                        onChange={(e) => setDialogueCustom(e.target.value)}
                        onBlur={handleDialogueCustomBlur}
                        className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    </label>
                  ) : null}

                  <div className="flex flex-col gap-2">
                    <span className="text-body-sm font-medium">{t("settings.audio.rate")}</span>
                    <div className="flex items-center gap-3">
                      <input
                        data-testid="settings-audio-rate-slider"
                        type="range"
                        min={-50}
                        max={50}
                        step={5}
                        value={rateSliderValue}
                        onChange={handleRateSlider}
                        onBlur={handleRateSliderBlur}
                        className="flex-1 accent-accent"
                        aria-label={t("settings.audio.rate") as string}
                      />
                      <input
                        data-testid="settings-audio-rate"
                        type="number"
                        value={rateNum}
                        onChange={handleRateNumberChange}
                        onBlur={handleRateNumberBlur}
                        min={-100}
                        max={100}
                        step={5}
                        className="h-9 w-20 rounded-md border border-input bg-card px-2 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label={t("settings.audio.rate") as string}
                      />
                      <span className="text-body-sm text-muted-foreground">%</span>
                    </div>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.rate")}</span>
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.audio.bitrate")}</span>
                    <select
                      data-testid="settings-audio-bitrate"
                      value={audioBitrate}
                      onChange={handleBitrateChange}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {BITRATE_OPTIONS.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.bitrate")}</span>
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        data-testid="settings-audio-normalize"
                        checked={normalizeAudio}
                        onChange={handleNormalizeToggle}
                        className="h-4 w-4 accent-accent"
                      />
                      <span className="text-body-sm font-medium">{t("settings.audio.normalize")}</span>
                    </span>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.normalize")}</span>
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        data-testid="settings-audio-trim"
                        checked={trimSilence}
                        onChange={handleTrimToggle}
                        className="h-4 w-4 accent-accent"
                      />
                      <span className="text-body-sm font-medium">{t("settings.audio.trim")}</span>
                    </span>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.trim")}</span>
                  </label>
                </div>
              </section>

              {/* TTS engine (local Piper) */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.engine.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.engine.title")}</h3>
                <div className="mt-4 space-y-4">
                  <div className="flex flex-col gap-2">
                    <span className="text-body-sm font-medium">{t("settings.engine.label")}</span>
                    <div className="flex flex-wrap gap-2" role="group" aria-label={t("settings.engine.label") as string}>
                      {(["auto", "edge", "local"] as const).map((opt) => (
                        <button
                          key={opt}
                          type="button"
                          data-testid={`settings-engine-${opt}`}
                          onClick={() => handleEngineChange(opt)}
                          aria-pressed={engine === opt}
                          disabled={opt === "local" && !piperAvailable}
                          className={`h-9 rounded-md border px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60 ${
                            engine === opt
                              ? "border-accent bg-accent/10 font-medium text-accent"
                              : "border-input bg-card text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          {t(`settings.engine.${opt}`)}
                        </button>
                      ))}
                    </div>
                    <span className="text-body-sm text-muted-foreground">{t("settings.engine.helper")}</span>
                    {!piperAvailable && (
                      <div className="flex flex-col gap-2">
                        <span data-testid="settings-engine-nopiper" className="text-body-sm text-muted-foreground">
                          {t("settings.engine.noPiper")}
                        </span>
                        <button
                          type="button"
                          data-testid="settings-engine-install"
                          disabled={engineBusy}
                          onClick={() => void handleEnsureLocalEngine()}
                          className="h-9 w-fit rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {engineBusy ? t("settings.engine.installing") : t("settings.engine.install")}
                        </button>
                      </div>
                    )}
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.localVoice.label")}</span>
                    <input
                      data-testid="settings-local-voice"
                      list="piper-voice-catalog"
                      value={localVoice}
                      onChange={handleLocalVoiceChange}
                      onBlur={handleLocalVoiceBlur}
                      placeholder={defaultLocalVoice}
                      autoComplete="off"
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <datalist id="piper-voice-catalog">
                      {localVoiceCatalog.map((v) => (
                        <option key={v.id} value={v.id}>
                          {`${v.name} · ${v.language} · ${v.quality} · ${v.sizeMb} MB${v.downloaded ? " ✓" : ""}`}
                        </option>
                      ))}
                    </datalist>
                    <span className="text-body-sm text-muted-foreground" data-testid="settings-local-voice-hint">
                      {localVoiceCatalog.length
                        ? `${t("settings.localVoice.catalogue") as string}: ${localVoiceCatalog.length}${
                            selectedLocalVoiceHint ? ` · ${selectedLocalVoiceHint}` : ""
                          }`
                        : (t("settings.localVoice.helper") as string)}
                    </span>
                  </label>
                    <label className="mt-1 flex items-center gap-2">
                      <input
                        type="checkbox"
                        data-testid="settings-local-cuda"
                        checked={localCuda}
                        onChange={(e) => void handleLocalCudaChange(e.target.checked)}
                        className="h-4 w-4 accent-[var(--accent)]"
                      />
                      <span className="text-body-sm">{t("settings.localVoice.cuda")}</span>
                    </label>

                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      data-testid="settings-local-download"
                      disabled={localBusy || !piperAvailable}
                      onClick={() => void handleDownloadLocalVoice()}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {localBusy ? t("settings.localVoice.downloading") : t("settings.localVoice.download")}
                    </button>
                    <button
                      type="button"
                      data-testid="settings-local-redownload"
                      disabled={localBusy || !piperAvailable}
                      onClick={() => void handleRedownloadLocalVoice()}
                      title={t("settings.localVoice.redownloadTitle") as string}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {t("settings.localVoice.redownload")}
                    </button>
                    <span data-testid="settings-local-status" className="text-body-sm text-muted-foreground">
                      {localMsg || (localVoiceList.find((v) => v.id === (localVoice || defaultLocalVoice))?.downloaded
                        ? t("settings.localVoice.ready")
                        : t("settings.localVoice.notDownloaded"))}
                    </span>
                  </div>
                </div>
              </section>

              {/* Performance */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.performance.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.performance.title")}</h3>
                <div className="mt-4 space-y-4">
                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.performance.parallel")}</span>
                    <select
                      data-testid="settings-perf-parallel"
                      value={String(parallel)}
                      onChange={handleParallelChange}
                      onBlur={handleParallelBlur}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {[1, 2, 3, 4, 5, 6].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.parallel")}</span>
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.performance.chunkSize")}</span>
                    <input
                      data-testid="settings-perf-chunk"
                      type="number"
                      value={chunkSize}
                      min={500}
                      max={5000}
                      step={100}
                      onBlur={handleChunkBlur}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") {
                          setChunkSize(500);
                          return;
                        }
                        const v = parseInt(raw, 10);
                        if (Number.isFinite(v)) setChunkSize(v);
                      }}
                    />
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.chunkSize")}</span>
                  </label>

                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.performance.retries")}</span>
                    <input
                      data-testid="settings-perf-retries"
                      type="number"
                      value={retries}
                      min={1}
                      max={10}
                      step={1}
                      onBlur={handleRetriesBlur}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") {
                          setRetries(1);
                          return;
                        }
                        const v = parseInt(raw, 10);
                        if (Number.isFinite(v)) setRetries(v);
                      }}
                    />
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.retries")}</span>
                  </label>
                </div>
              </section>

              {/* Scrape */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.scrape.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.scrape.title")}</h3>
                <div className="mt-4 space-y-4">
                  <label className="flex flex-col gap-1">
                    <span className="text-body-sm font-medium">{t("settings.scrape.delay")}</span>
                    <select
                      data-testid="settings-scrape-delay"
                      value={isScrapeCustom ? "custom" : String(scrapeDelay)}
                      onChange={handleScrapeDelayChange}
                      className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <option value="3000">3000</option>
                      <option value="4000">4000</option>
                      <option value="5000">5000</option>
                      <option value="custom">{t("settings.scrape.custom")}</option>
                    </select>
                    <span className="text-body-sm text-muted-foreground">{t("settings.helper.scrapeDelay")}</span>
                  </label>

                  {isScrapeCustom ? (
                    <label className="flex flex-col gap-1">
                      <span className="text-body-sm font-medium">{t("settings.scrape.custom")}</span>
                      <input
                        data-testid="settings-scrape-custom"
                        type="number"
                        value={scrapeCustom}
                        min={0}
                        max={20000}
                        step={100}
                        onBlur={handleScrapeCustomBlur}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (raw === "") {
                            setScrapeCustom(0);
                            return;
                          }
                          const v = parseInt(raw, 10);
                          if (Number.isFinite(v)) setScrapeCustom(v);
                        }}
                        className="h-9 rounded-md border border-input bg-card px-3 text-body focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    </label>
                  ) : null}

                  <label className="flex items-center justify-between gap-4">
                    <div className="flex flex-col">
                      <span className="text-body-sm font-medium">{t("settings.scrape.safeMode")}</span>
                      <span className="text-body-sm text-muted-foreground">{t("settings.helper.safeMode")}</span>
                    </div>
                    <input
                      data-testid="settings-scrape-safe"
                      type="checkbox"
                      checked={safeMode}
                      onChange={handleSafeModeChange}
                      className="h-4 w-4 rounded border-input"
                      role="switch"
                      aria-checked={safeMode}
                    />
                  </label>
                </div>
              </section>

              {/* Outputs */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.outputs.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.outputs.title")}</h3>
                <p className="text-body-sm text-muted-foreground mt-1">{t("settings.helper.outputs")}</p>
                <div className="mt-4 space-y-3">
                  <label className="flex items-center justify-between gap-4">
                    <span className="text-body-sm font-medium">{t("settings.outputs.keepEPUB")}</span>
                    <input
                      data-testid="settings-output-keepEPUB"
                      type="checkbox"
                      checked={keepEPUB}
                      onChange={handleKeepChange("keepEPUB")}
                      className="h-4 w-4 rounded border-input"
                      role="switch"
                      aria-checked={keepEPUB}
                    />
                  </label>
                  <label className="flex items-center justify-between gap-4">
                    <span className="text-body-sm font-medium">{t("settings.outputs.keepMP3")}</span>
                    <input
                      data-testid="settings-output-keepMP3"
                      type="checkbox"
                      checked={keepMP3}
                      onChange={handleKeepChange("keepMP3")}
                      className="h-4 w-4 rounded border-input"
                      role="switch"
                      aria-checked={keepMP3}
                    />
                  </label>
                  <label className="flex items-center justify-between gap-4">
                    <span className="text-body-sm font-medium">{t("settings.outputs.keepM4B")}</span>
                    <input
                      data-testid="settings-output-keepM4B"
                      type="checkbox"
                      checked={keepM4B}
                      onChange={handleKeepChange("keepM4B")}
                      className="h-4 w-4 rounded border-input"
                      role="switch"
                      aria-checked={keepM4B}
                    />
                  </label>
                </div>
              </section>

              {/* Updates */}
              <section className="rounded-lg border bg-card p-6 shadow-sm" aria-label={t("settings.updates.title") as string}>
                <h3 className="text-heading font-semibold">{t("settings.updates.title")}</h3>
                <div className="mt-4 space-y-3">
                  <label className="flex items-center justify-between gap-4">
                    <span className="text-body-sm font-medium">{t("settings.updates.auto")}</span>
                    <input
                      data-testid="settings-updates-auto"
                      type="checkbox"
                      checked={updateAuto}
                      onChange={handleUpdateAutoChange}
                      className="h-4 w-4 rounded border-input"
                      role="switch"
                      aria-checked={updateAuto}
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      data-testid="settings-updates-check"
                      onClick={handleCheckNow}
                      disabled={checkStatus === "checking"}
                      className="rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    >
                      {t("settings.updates.check")}
                    </button>
                    {checkStatus ? (
                      <span data-testid="settings-updates-status" className="text-body-sm text-muted-foreground">
                        {checkStatus === "checking" ? t("settings.updates.checking") : checkStatus}
                      </span>
                    ) : null}
                  </div>
                </div>
              </section>
            </>
          )}
    </div>
  );

  const toastNode = toast ? (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-testid="settings-toast"
      className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-md bg-card border shadow-lg px-4 py-2 text-body-sm"
    >
      {toast}
    </div>
  ) : null;

  if (isInline) {
    return (
      <section data-testid="settings-inline" aria-label={t("settings.title") as string}>
        {body}
        {toastNode}
      </section>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="presentation"
      onClick={onClose}
      data-testid="settings-overlay"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("settings.title") as string}
        data-testid="settings-dialog"
        tabIndex={-1}
        className="relative max-h-[90vh] w-full max-w-[560px] overflow-auto rounded-lg border bg-card shadow-lg focus-visible:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b bg-card px-6 py-4">
          <h2 className="text-heading font-semibold">{t("settings.title")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("settings.title") as string}
            className="rounded-md p-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="settings-close"
          >
            ×
          </button>
        </div>
        {body}
        {toastNode}
      </div>
    </div>
  );
}
