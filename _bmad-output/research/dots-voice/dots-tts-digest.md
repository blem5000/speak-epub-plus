# dots.tts digest — local voice-cloning backend feasibility (Windows, no NVIDIA)

Research date: 2026-09-08. Rule: every factual claim below carries its source URL; items that could not be verified are marked UNVERIFIED.

## 1. Dependencies (torch range, CUDA, XPU/DirectML/OpenVINO/ONNX)

- `pyproject.toml` requires `torch>=2.8.0` and `torchaudio>=2.8.0` (lower bounds only, no upper pin), `requires-python >=3.10,<3.13`, plus `transformers>=4.57.0`, `librosa`, `soundfile`, `safetensors`, `torchdiffeq`, `WeTextProcessing`, `gradio>=6.17,<7`. No CUDA-specific torch index/extra is declared in pyproject. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/pyproject.toml, 2026-09-08)
- Reproducible pins in `constraints/recommended.txt`: `torch==2.8.0`, `torchaudio==2.8.0`, `transformers==4.57.0`, `numpy==2.2.6`. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/constraints/recommended.txt, 2026-09-08)
- No separate CUDA build is hard-required by the package metadata, but the runtime assumes a CUDA torch build on GPU machines: `runtime.py::_check_torch_env` warns "install a torch build matching your CUDA driver" when `torch.cuda` is unavailable, and device selection is `cuda` if available else `cpu`. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py, 2026-09-08)
- CPU fallback exists but is degraded: half precision (`bfloat16`/`float16`) without CUDA raises `RuntimeError` — CPU callers must pass `precision='float32'`; CPU path also forces `torch.set_num_threads(1)`. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py, 2026-09-08)
- No Intel XPU, DirectML, OpenVINO, or ONNX support is mentioned in any of the files reviewed (`pyproject.toml`, `constraints/recommended.txt`, `src/dots_tts/runtime.py`, `src/dots_tts/cli.py`, `README.md`). A full-repo code search was not performed, so support hiding elsewhere is UNVERIFIED, but all reviewed integration points are CUDA-or-CPU only. (srcs: same raw URLs above + https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md, 2026-09-08)
- Default inference precision is `bfloat16` (CLI `--precision` default, `from_pretrained(precision="bfloat16")`). (srcs: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/cli.py and .../src/dots_tts/runtime.py, 2026-09-08)

## 2. Checkpoint sizes (HuggingFace, dots-studio org)

Snapshot size is identical across all four repos (~5.16 GB; `-mf` page shows 5.17 GB). Per-file sizes from the file-tree pages:

| File | Size |
|---|---|
| `model.safetensors` | 4.4 GB |
| `vocoder.safetensors` | 724 MB |
| `speaker_encoder.safetensors` | 29.2 MB |
| `tokenizer.json` / `vocab.json` / `merges.txt` | 11.4 MB / 2.78 MB / 1.67 MB |
| configs, tokenizer misc, `latent_stats.pt` | KBs |

(srcs: https://huggingface.co/dots-studio/dots.tts-soar/tree/main, https://huggingface.co/dots-studio/dots.tts-mf/tree/main, https://huggingface.co/dots-studio/dots.tts-base/tree/main, https://huggingface.co/dots-studio/dots.tts-mf-2steps/tree/main — all 2026-09-08)

- Weight precision is BF16 for all: API reports `safetensors.parameters.BF16 = 2198091778` (~2.2B) for `-base`, `-soar`, `-mf-2steps`, and `2199404546` for `-mf` (slightly higher — extra MeanFlow duration embedding). (srcs: https://huggingface.co/api/models/dots-studio/dots.tts-soar, .../dots.tts-base, .../dots.tts-mf, .../dots.tts-mf-2steps — all 2026-09-08)
- Note: the API `usedStorage` field reads 23.5 GB for the older repos vs 5.16 GB for `-mf-2steps`; that field includes git history (the `-mf-2steps` history was sanitized to 2 commits), so the tree-page snapshot total (~5.16 GB download) is the planning number, not `usedStorage`. (srcs: same tree + API URLs, 2026-09-08)
- `-mf-2steps` additionally ships a `SHA256SUMS` file. (src: https://huggingface.co/dots-studio/dots.tts-mf-2steps/tree/main, 2026-09-08)
- `-mf-1step` per-file sizes are UNVERIFIED (tree page not fetched; same 2B backbone per README table).

## 3. RAM/VRAM guidance, CPU inference

- No official minimum RAM/VRAM figure is published. Open issue #48 ("what gpu cpu and ram it needs") has no maintainer answer visible. (src: https://github.com/studio-dots-ai/dots.tts/issues/48, 2026-09-08)
- Only official memory numbers are GPU peak-alloc from the README Efficiency section (single H800, bf16, `--optimize`, streaming): SOAR 5.65 GB (<10 s audio) → 6.53 GB (<20 s) → 7.86 GB (<41 s) → 10.51 GB (<82 s); MF 5.30 → 5.47 → 5.74 → 6.29 GB. So ~6 GB VRAM covers short-form MF, ~11 GB for long-form SOAR — on CUDA. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md, 2026-09-08)
- Official speed numbers are CUDA-only: steady-state RTF p50 SOAR 0.20 (clone) / 0.18 (text-only), MF 0.15 / 0.13; first-chunk p50 SOAR 225 ms / 69 ms, MF 204 ms / 68 ms; `--optimize` cold start ≈ 3 min `torch.compile` warmup on H800. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md, 2026-09-08)
- No official CPU RTF exists. Sole in-repo CPU-adjacent datapoint is issue #25 (title only, empty body, no response): MacBook Pro M1 Pro, `mf-int4`, "1 minute of audio needs nearly 1 h" (≈ RTF 60). Third-party `mf-int4` quant is not an official artifact. (src: https://github.com/studio-dots-ai/dots.tts/issues/25 and https://github.com/studio-dots-ai/dots.tts/issues, 2026-09-08)
- Community ports imply CPU paths but are unofficial: `audio.cpp` (ggml C++, "CPU/CUDA/Vulkan/Metal, no Python"), `dots-tts-mlx` / `mlx-swift-dots-tts` (Apple Silicon). No Intel Arc / Snapdragon X Elite reports found — feasibility on both target machines is UNVERIFIED. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md, 2026-09-08)

## 4. Windows support

- `pyproject.toml` OS classifiers list only `POSIX :: Linux` and `MacOS` — no Windows classifier. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/pyproject.toml, 2026-09-08)
- The repo's only CI workflow is `release.yml`: `runs-on: ubuntu-latest`, PyPI publish only, no tests, no Windows/macOS matrix. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/.github/workflows/release.yml + https://api.github.com/repos/studio-dots-ai/dots.tts/contents/.github/workflows, 2026-09-08)
- No Windows issue or Windows documentation section was found in the files reviewed; Windows functionality is UNVERIFIED — treat as untested/unsupported upstream. Whether PyTorch ships Windows ARM64 wheels for Snapdragon X Elite is likewise UNVERIFIED.
- Practical consequence: the Python sidecar would run CPU-only `float32` (per §1) with `torch.set_num_threads(1)` hardcoded — expected to be very slow for a 2B AR model; no backend exists for Intel Arc iGPU (no XPU/DirectML/ONNX path, §1).

## 5. Python API + CLI for file-based synthesis

- Entry: `DotsTtsRuntime.from_pretrained(model_name_or_path, *, revision=None, cache_dir=None, precision="bfloat16", optimize=False, max_generate_length=500, max_sequence_length=2048, vocoder_merge_steps=4, warmup_on_optimize=True)`; accepts a local dir or HF repo id (downloaded via `snapshot_download` and cached). (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py, 2026-09-08)
- `generate(*, text, prompt_audio_path=None, prompt_text=None, template_name=None, language=None, speaker_scale=1.5, ode_method=None, num_steps=None, guidance_scale=None, normalize_text=False, profile_inference=False, log_profile_calls=False)` returns `{"fid","audio","sample_rate","time_used","rtf","profiling"}`; `audio` is a float tensor, `result["sample_rate"]` is the rate to pass to `sf.write`. `generate_stream` takes identical args and yields `(1, samples)` chunks. `prompt_text` without `prompt_audio_path` raises `ValueError`. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py, 2026-09-08)
- Output sample rate confirmed 48 kHz: `config.json` → `vocoder.sample_rate = 48000`; runtime sets `self.sample_rate` from model config; README architecture states "48 kHz AudioVAE". (srcs: https://huggingface.co/dots-studio/dots.tts-base/raw/main/config.json, https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py, https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md — all 2026-09-08)
- Reference-audio guidance confirmed ~10 s: Usage Tips "Keep the reference audio around 10s. Longer audio won't yield better results"; config sets `xvec_max_audio_seconds = 10.0`. `prompt_text` must be the exact transcript of the reference audio; mismatches degrade stability. Cloning modes: with transcript = continuation cloning (best SIM); audio-only = x-vector cloning; neither = random voice (only for fine-tuned single-speaker). (srcs: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md + config.json URL above, 2026-09-08)
- Sampling contracts: `-base`/`-soar` NFE 10–32 (default 10), CFG 1.2; `-mf` NFE 4 recommended, CFG fused (guidance flag no-op); `-mf-2steps` fixed NFE 2 sCM and `-mf-1step` fixed NFE 1 — omit sampling options, incompatible overrides are rejected. (srcs: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md, https://huggingface.co/dots-studio/dots.tts-soar, https://huggingface.co/dots-studio/dots.tts-mf — all 2026-09-08)
- CLI (`dots.tts`): `--model-name-or-path` (required), `--text` (required), `--output` (default `output.wav`), `--prompt-audio`, `--prompt-text`, `--precision` (default `bfloat16`), `--seed` (default 42), `--language`, `--template-name`, `--ode-method`, `--num-steps`, `--guidance-scale`, `--speaker-scale` (default 1.5), `--max-generate-length` (500), `--max-sequence-length` (2048), `--normalize-text`, `--profile-inference[-calls]`, `--revision`, `--cache-dir`. (src: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/cli.py, 2026-09-08)

## 6. License (code + checkpoints)

- Code license is Apache-2.0: `pyproject.toml` (`license = "Apache-2.0"`), `LICENSE` file text, README badge. Copyright line: "Copyright 2026 dots.tts Team, RedNote". (srcs: https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/pyproject.toml, https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/LICENSE, https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md — all 2026-09-08)
- Checkpoints are also Apache-2.0: README License section states "dots.tts code and released checkpoints are licensed under Apache-2.0"; each HF repo's metadata declares `license: apache-2.0` (`-soar`, `-mf`, `-base`, `-mf-2steps` API `cardData`/`tags`). No separate model license file was found in the files reviewed. (srcs: README URL above + https://huggingface.co/api/models/dots-studio/dots.tts-soar, .../dots.tts-mf, .../dots.tts-base, .../dots.tts-mf-2steps — all 2026-09-08)

## Bottom line for the sidecar plan

- Recommended checkpoint for local use is `-mf-2steps` (fixed 2-step, best speed/quality trade-off) or `-mf` (NFE 4); both ≈ 5.16 GB download, BF16. But on the two target machines there is no GPU path (no XPU/DirectML/ONNX in reviewed files) and CPU is forced to `float32` single-threaded — expect far worse than the only community CPU datapoint (≈ RTF 60 on M1 Pro, unofficial int4). Native-feasibility on Core Ultra 5 125H iGPU and Snapdragon X Elite is UNVERIFIED; realistic options are the unofficial `audio.cpp` CPU/Vulkan port (UNVERIFIED for these chips) or a server-side GPU with the sidecar as a thin client.

## Sources (all accessed 2026-09-08)

- https://github.com/studio-dots-ai/dots.tts
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/pyproject.toml
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/constraints/recommended.txt
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/runtime.py
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/src/dots_tts/cli.py
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/README.md
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/LICENSE
- https://raw.githubusercontent.com/studio-dots-ai/dots.tts/main/.github/workflows/release.yml
- https://api.github.com/repos/studio-dots-ai/dots.tts/contents/.github/workflows
- https://huggingface.co/dots-studio/dots.tts-soar (+ /tree/main)
- https://huggingface.co/dots-studio/dots.tts-mf (+ /tree/main)
- https://huggingface.co/dots-studio/dots.tts-base (+ /tree/main)
- https://huggingface.co/dots-studio/dots.tts-mf-2steps (+ /tree/main)
- https://huggingface.co/api/models/dots-studio/dots.tts-soar
- https://huggingface.co/api/models/dots-studio/dots.tts-mf
- https://huggingface.co/api/models/dots-studio/dots.tts-base
- https://huggingface.co/api/models/dots-studio/dots.tts-mf-2steps
- https://huggingface.co/dots-studio/dots.tts-base/raw/main/config.json
- https://github.com/studio-dots-ai/dots.tts/issues
- https://github.com/studio-dots-ai/dots.tts/issues/48
- https://github.com/studio-dots-ai/dots.tts/issues/25
