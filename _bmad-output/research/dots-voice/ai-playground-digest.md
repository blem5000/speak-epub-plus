# ai-playground/TTS digest — dots.tts voice-cloning reference

Research date: 2026-09-08. Rule: every factual claim below carries its source URL + access date; items that could not be verified are marked UNVERIFIED.

## 0. What this reference is

- `ai-playground/TTS` is described as "support scripts for use with dots.tts in a local environment", with `server_dotsTTS.py` as "a simple REST API around dots.tts" plus analogous servers for Qwen3-TTS and OmniVoice (Chatterbox server also present in folder but omitted from README list). (src: https://github.com/scorbo2/ai-playground/tree/master/TTS, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/README.md, 2026-09-08)
- All server scripts expose `POST /synthesize` (clone voice from reference audio) and `GET /health` (health check). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/README.md, 2026-09-08)
- Setup pattern is copy server file into the engine checkout then run with uvicorn, e.g. `cp server_dotsTTS.py /some/path/to/dots.tts/` then `uvicorn server_dotsTTS:app --host 0.0.0.0 --port 8181`. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/README.md, 2026-09-08)
- The `TalkWithMe` app "makes heavy use of these server scripts for speech synthesis" as extended usage example. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/README.md, 2026-09-08)
- `server_generification.md` status is explicitly "PROPOSAL — under review, no code written yet" dated 2026-08-30, covering capability-discovery unification across 4 engines. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_generification.md, 2026-09-08)

## 1. Directory listing (files, languages, sizes)

- Folder contains 9 files, no subfolders, per tree page + Contents API. (src: https://github.com/scorbo2/ai-playground/tree/master/TTS, 2026-09-08; src: https://api.github.com/repos/scorbo2/ai-playground/contents/TTS?ref=master, 2026-09-08)
- Sizes below are `size` (bytes) from the Contents API accessed 2026-09-08 (src: https://api.github.com/repos/scorbo2/ai-playground/contents/TTS?ref=master, 2026-09-08):

| File | Language | Size (bytes / ~KB) |
|---|---|---|
| `README.md` | Markdown | 1984 / ~1.9 KB |
| `parse.py` | Python | 5009 / ~4.9 KB |
| `server_chatterbox.py` | Python | 19549 / ~19.1 KB |
| `server_dotsTTS.py` | Python | 14260 / ~13.9 KB |
| `server_generification.md` | Markdown | 24334 / ~23.8 KB |
| `server_omnivoice.py` | Python | 16872 / ~16.5 KB |
| `server_qwen3TTS.py` | Python | 13253 / ~12.9 KB |
| `speak.py` | Python | 6028 / ~5.9 KB |
| `speak.sh` | Bash | 4969 / ~4.9 KB |

- Language mix: 5× Python (`.py`), 1× Bash (`.sh`), 2× Markdown (`.md`) plus README; total ~103 KB. (src: https://api.github.com/repos/scorbo2/ai-playground/contents/TTS?ref=master, 2026-09-08)
- Last-commit dates / authors per file are UNVERIFIED (tree-page commit metadata not fetched; only file names + README excerpt + API sizes verified). (src: https://github.com/scorbo2/ai-playground/tree/master/TTS, 2026-09-08)

## 2. Which TTS engine(s) demonstrated (dots.tts? checkpoint? others?)

- `server_dotsTTS.py` demonstrates dots.tts with `MODEL_NAME_OR_PATH = "rednote-hilab/dots.tts-soar"` (comment notes alternative is local dir path or HF id; code comment references `rednote-hilab/dots.tts-soar` pulling from local cache or downloading). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08)
- `server_qwen3TTS.py` demonstrates Qwen3-TTS with `MODEL_NAME_OR_PATH = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"` (comment notes HF id or local path alternative). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_qwen3TTS.py, 2026-09-08)
- `server_omnivoice.py` demonstrates OmniVoice with `MODEL_NAME_OR_PATH = "k2-fsa/OmniVoice"` (comment notes HF id or local dir alternative). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_omnivoice.py, 2026-09-08)
- `server_chatterbox.py` demonstrates Chatterbox Multilingual (`ResembleAI/chatterbox` via `chatterbox.mtl_tts.ChatterboxMultilingualTTS.from_pretrained`), T3 checkpoint selected by `CHATTERBOX_T3_MODEL` env (default `v3`, alt `v2` / `t3_mtl23ls_v2|v3` / custom `.safetensors`); weights downloaded from HuggingFace on first start. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_chatterbox.py, 2026-09-08)
- Client helpers `speak.py` / `speak.sh` target the dots.tts REST API contract by default (`speak.py` docstring "TTS wrapper for dots.tts REST API"). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08)
- `parse.py` is not a TTS engine; it is an OpenAI-compatible STT client (`/v1/audio/transcriptions`) for transcribing audio. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/parse.py, 2026-09-08)

## 3. Exact dots.tts integration pattern (what to copy)

Flow in `server_dotsTTS.py` (src for all bullets in this section unless noted: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08):

- **1. Imports + path fix:** `from dots_tts.runtime import DotsTtsRuntime`, `from dots_tts.utils.util import seed_everything`; script prepends repo-root and `src/` to `sys.path` so `dots_tts` resolves when server file is copied into dots.tts checkout.
- **2. Model load (once, lazy + startup preload):** global `_runtime: DotsTtsRuntime | None`; `_get_runtime()` does `DotsTtsRuntime.from_pretrained(MODEL_NAME_OR_PATH, precision="bfloat16")`; `@app.on_event("startup")` calls `_get_runtime()` so first request is fast.
- **3. Request schema to copy:** `SynthesisRequest { text: str, audio_base64: str (~10s WAV b64), prompt_text: str (exact transcript), seed?: 1-1000 (random if omitted), num_steps?: 10-20 (random if omitted), guidance_scale=1.2, speaker_scale=1.5, ode_method="euler"|"midpoint"|"rk4", language?: str|None (auto) }`.
- **4. Reference-audio cloning call:**
  ```python
  seed_everything(seed)
  raw_audio = base64.b64decode(req.audio_base64)
  prompt_audio_path = _write_temp_wav(raw_audio)  # /tmp/dots_tts_rest_api/<uuid>.wav
  try:
      result = runtime.generate(
          text=req.text,
          prompt_audio_path=prompt_audio_path,
          prompt_text=req.prompt_text,
          ode_method=req.ode_method,
          num_steps=num_steps,
          guidance_scale=req.guidance_scale,
          speaker_scale=req.speaker_scale,
          language=req.language,
      )
  finally:
      _cleanup_temp(prompt_audio_path)
  ```
- **5. Audio save (tensor→WAV→b64):**
  ```python
  buffer = io.BytesIO()
  sf.write(buffer, result["audio"].float().cpu().squeeze().numpy(),
           result["sample_rate"], format="WAV", subtype="PCM_16")
  audio_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
  # response: { audio_base64, sample_rate, seed, num_steps, fid, time_used, rtf }
  ```
  `rtf`/`time_used` sanitizers map inf/nan → None/0.0 so JSON never fails.
- **6. REST surface:** `GET /` (HTML landing), `GET /health → {status:"ok", serverType:"dots.tts", model}`, `POST /synthesize → SynthesisResponse`; global exception handler returns `500 {"detail": ...}` instead of blank detail.
- **Client call pattern to copy (`speak.py` / `speak.sh`):** base64-encode reference WAV, clean transcript whitespace, POST JSON `{text, prompt_text, audio_base64, seed, num_steps[, language]}` to `/synthesize`, decode `audio_base64` response to WAV and save/play. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08)
  - `speak.py` defaults: `--server http://saturn-lm:8181/synthesize`, `--ref-audio /home/scorbett/audio/reference.wav`, `--ref-audio-transcript /home/scorbett/audio/reference.txt`, `--steps 12`, `--language en`; saves via `--output-file` else plays via `aplay`. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08)
  - `speak.sh` equivalent: `SERVER_URL="http://saturn-lm:8000/synthesize"`, `num_steps: 12`, `seed: null`, uses `curl+jq+base64+aplay`, `mktemp` + trap cleanup. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08)
- Key difference vs Chatterbox to note when porting: Chatterbox request has no `prompt_text` (conditions purely on audio); dots.tts/OmniVoice/Qwen require both `audio_base64` + `prompt_text`. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_chatterbox.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08)

## 4. Hardware / device handling

- **dots.tts (`server_dotsTTS.py`):** fixed `DEFAULT_PRECISION = "bfloat16"` passed to `from_pretrained`; no explicit device/`device_map` argument in reviewed file; lazy singleton + startup preload; shutdown does `del _runtime.model; _runtime=None; torch.cuda.empty_cache()`. CUDA-only cleanup (no `is_available` guard in this file). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08)
- **Chatterbox (`server_chatterbox.py`):** device via `CHATTERBOX_DEVICE` env (`cuda|mps|cpu`, default `cuda`, validated fail-fast); `ChatterboxMultilingualTTS.from_pretrained(device=DEVICE, t3_model=T3_MODEL)`; host/port via `CHATTERBOX_HOST/PORT` (defaults `0.0.0.0:8000`); global `threading.Lock` serializes `generate()` because fresh `audio_prompt_path` rewrites shared `conds` state; custom `seed_everything` (random+numpy+torch+cuda); shutdown guards with `if torch.cuda.is_available()`. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_chatterbox.py, 2026-09-08)
- **Qwen3-TTS (`server_qwen3TTS.py`):** hardcoded `device_map="cuda:0"`, `dtype=torch.bfloat16`; tries `attn_implementation="flash_attention_2"` then falls back to default attention on exception; `torch.manual_seed(seed)` per request; timing via `torch.cuda.Event` + `torch.cuda.synchronize()`; shutdown drops runtime + `torch.cuda.empty_cache()`. No CPU fallback in reviewed file. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_qwen3TTS.py, 2026-09-08)
- **OmniVoice (`server_omnivoice.py`):** `DEFAULT_PRECISION="bfloat16"` mapped via `_get_dtype()` (`float16|float32|bfloat16`) to `torch_dtype`; `OmniVoice.from_pretrained(MODEL, device_map="cuda", torch_dtype=dtype)`; exposes `model.sampling_rate` / `model.device`; per-request `seed_everything(seed)`; timing via `time.perf_counter()`; shutdown `del model + torch.cuda.empty_cache()`. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_omnivoice.py, 2026-09-08)
- No DirectML / XPU / OpenVINO / ONNX / MPS handling appears in dots.tts, Qwen, or OmniVoice server files reviewed; only Chatterbox advertises `mps|cpu` option. Full-repo search not performed, so absence elsewhere is UNVERIFIED. (srcs: the four `server_*.py` raw URLs above, 2026-09-08)

## 5. Recording / preparing reference voice audio

- **Requirement:** dots.tts-family servers expect ~10 s WAV as base64 plus exact transcript: field help says "Reference audio sample (~10 s WAV)" and "Exact transcript of the reference audio". (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08; identical wording in https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_omnivoice.py, 2026-09-08; https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_qwen3TTS.py, 2026-09-08)
- **Quality guidance (`speak.sh` header):** "8-12s of very clear speech" for `reference_audio.wav` plus "(one line) an exact transcript" in `reference_transcript.txt`; these "are used for voice cloning". (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08)
- **Transcript sanitization to copy:** shell `tr '\n' ' ' | sed 's/  */ /g; s/ *$//'`; Python `load_and_clean_transcript()` does `" ".join(raw.split())` (collapse all whitespace, trim). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08)
- **Audio encoding to copy:** `base64 -w 0 < WAV` (shell) / `base64.b64encode(open(path,"rb").read()).decode("utf-8")` (Python); server writes bytes verbatim to `/tmp/<engine>_rest_api/<uuid>.wav` because runtime expects a file path. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08)
- **Making the transcript (`parse.py`):** send audio file as `multipart/form-data {file, response_format:"json"}` to OpenAI-compatible `/v1/audio/transcriptions` (default `http://saturn-lm:5000/v1/audio/transcriptions`), print `Language: <lang>` + text; supports wav/mp3/flac/ogg/opus/m4a/webm/aac/pcm via extension→MIME map. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/parse.py, 2026-09-08)
- **Validation nuance (Chatterbox only):** header-decodes with `soundfile.info`, rejects `<2.0 s` (`MIN_PROMPT_DURATION_S`), caps request b64 at 10M chars, notes "model uses only its first 10 s" and any soundfile-decodable container works. dots.tts-file validation details beyond base64-decode are UNVERIFIED in reviewed file (no duration check present). (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_chatterbox.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py, 2026-09-08)
- No microphone-recording code is present in reviewed TTS files; `speak.*` play back via `aplay` (or `--output-file` save in `speak.py`). Live-capture workflow is UNVERIFIED. (src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py, 2026-09-08; src: https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh, 2026-09-08)

## Sources (all accessed 2026-09-08)

- https://github.com/scorbo2/ai-playground/tree/master/TTS
- https://api.github.com/repos/scorbo2/ai-playground/contents/TTS?ref=master
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/README.md
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_dotsTTS.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_qwen3TTS.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_omnivoice.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_chatterbox.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/speak.sh
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/parse.py
- https://raw.githubusercontent.com/scorbo2/ai-playground/master/TTS/server_generification.md
