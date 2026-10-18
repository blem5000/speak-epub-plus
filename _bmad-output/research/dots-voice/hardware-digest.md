# Hardware digest: PyTorch transformer TTS 2B bf16 offline — Intel Ultra 5 125H iGPU vs Snapdragon X Elite (2026-09-08)

Scope: offline voice-cloning TTS in desktop app, no NVIDIA. Targets: (a) Core Ultra 5 125H Arc iGPU Windows x64, (b) Snapdragon X Elite Windows ARM64 CPU.

## 1. IPEX / XPU on Windows (Meteor Lake 125H)

- IPEX `v2.6.10+xpu` supports Intel Core Ultra with Arc Graphics based on PyTorch 2.6.0 [Source: https://intel.github.io/intel-extension-for-pytorch/xpu/2.6.10+xpu/tutorials/releases.html, accessed 2026-09-08].
- Meteor Lake-H (MTL-H) Windows support debuted as Prototype in `v2.1.40+xpu` on torch 2.1.0 [Source: https://intel.github.io/intel-extension-for-pytorch/xpu/2.6.10+xpu/tutorials/releases.html, accessed 2026-09-08].
- `v2.5.10+xpu` (torch 2.5.1) and `v2.8.10+xpu` (torch 2.8.0) list Core Ultra + Arc Graphics + Series 2 + Max/Flex families [Source: https://github.com/intel/intel-extension-for-pytorch/releases, accessed 2026-09-08].
- IPEX-LLM Windows GPU guide explicitly covers Core Ultra / 11–14th-gen iGPUs + Arc, with a worked example on Core Ultra 5 125H + Arc iGPU and `cpu_embedding=True` for small iGPU memory [Source: https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/install_windows_gpu.md, accessed 2026-09-08].
- PyTorch 2.6 added Windows XPU binary releases (torch/torchvision/torchaudio) for Core Ultra AI PCs + Arc A/B-series, simplifying install vs old oneAPI manual setup [Source: https://pytorch.org/blog/unlocking-pt-2-6-intel/, accessed 2026-09-08].
- IPEX is EOL end-March-2026; Intel states CPU/GPU support upstreamed into native PyTorch, no quarterly releases after 2.8, only critical fixes to March 2026 [Source: https://pytorch-extension.intel.com/installation?os=windows&package=pip&platform=gpu&version=v2.6.10%2Bxpu, accessed 2026-09-08] [Source: https://intel.github.io/intel-extension-for-pytorch/, accessed 2026-09-08].
- Implication for new app in late 2026: do NOT pin new work to `intel_extension_for_pytorch`; target upstream `torch` XPU wheels [Source: https://intel.github.io/intel-extension-for-pytorch/, accessed 2026-09-08].
- `torch.compile` on XPU is Beta via Inductor + Intel Triton extension (`pytorch-triton-xpu`), needs oneAPI DPC++ and cache clear [Source: https://intel.github.io/intel-extension-for-pytorch/xpu/latest/tutorials/features/torch_compile_gpu.html, accessed 2026-09-08].
- On native Windows XPU, `torch.compile` was staged: Stage 0 eager-only because Triton not on Windows, Stage 2 to enable `torch.compile`; experimental BKC needs source-built Triton + Level Zero SDK + MSVC [Source: https://github.com/pytorch/pytorch/issues/126719, accessed 2026-09-08] [Source: https://github.com/intel/torch-xpu-ops/discussions/1265, accessed 2026-09-08].
- XPU AMP defaults to bfloat16; float16 also supported on GPU [Source: https://intel.github.io/intel-extension-for-pytorch/xpu/2.3.110%2Bxpu/tutorials/features.html, accessed 2026-09-08].
- Whether `dots.tts` 2B AR + flow-matching head runs correctly under XPU `torch.compile`/bf16 on 125H in 2026 is UNVERIFIED (no published dots.tts+XPU report found).

## 2. PyTorch CPU inference on Windows x64 (2B)

- Weight math: 2B params × 2B bf16 ≈ 4 GB, × 4B fp32 ≈ 8 GB before KV-cache/runtime; analog: Qwen2.5-1.5B BF16 reports 2.95 GB and Qwen1.5-1.8B BF16 4.60 GB GPU memory at short context [Source: https://qwen.readthedocs.io/en/v2.5/benchmark/speed_benchmark.html, accessed 2026-09-08] [Source: https://qwen.readthedocs.io/en/v1.5/benchmark/hf_infer.html, accessed 2026-09-08]. Exact dots.tts 2B CPU RSS is UNVERIFIED.
- bf16 speed on CPU requires AVX512-BF16 or AMX; Cooper Lake was first x86 with native bf16 (1.4–2.2× over fp32 on TorchVision), AMX further boosts Xeon 4th-gen+ [Source: https://pytorch.org/blog/empowering-pytorch-on-intel-xeon-scalable-processors-with-bfloat16/, accessed 2026-09-08] [Source: https://www.intel.com/content/www/us/en/developer/articles/technical/pytorch-on-xeon-processors-with-bfloat16.html, accessed 2026-09-08].
- Core Ultra 5 125H ARK lists only `SSE4.1/4.2, AVX2` instruction extensions (no AVX-512/AMX shown); third-party spec lists `AVX, AVX2, AVX-VNNI, FMA3` only [Source: https://www.intel.com/content/www/us/en/products/sku/236848/intel-core-ultra-5-processor-125h-18m-cache-up-to-4-50-ghz/specifications.html, accessed 2026-09-08] [Source: https://www.notebookcheck.net/Intel-Core-Ultra-5-125H-Processor-Benchmarks-and-Specs.783325.0.html, accessed 2026-09-08].
- Consequence: bf16 on 125H CPU likely falls back to slow emulation; on laptop i7-13600P/Win11/PT2.9 CPU, fp16 was 28× slower and bf16 26× slower than fp32 on distilgpt2 generate (0.65/0.69 vs 18.1 tok/s) with no warning [Source: https://github.com/huggingface/transformers/issues/41867, accessed 2026-09-08]. Direct dots.tts bf16 RTF on 125H is UNVERIFIED.
- Best-case CPU recipe (Xeon): `torch.compile` + WOQ-int8/int4 + BFloat16 + SDPA gave ~3.8× over eager baseline on Llama-2-7B; SDXL bf16+compile+SDPA ~3.91× over fp32 [Source: https://pytorch.org/blog/genai-acceleration-intel-xeon/, accessed 2026-09-08].
- Rough LLM CPU anchor (not TTS): Qwen2.5-1.5B-Q8 llama.cpp on Ryzen 7800X3D did ~23 tok/s CPU vs ~190 tok/s on RTX 3090 [Source: https://www.reddit.com/r/LocalLLaMA/comments/1fq883g/qwen_25_cpu_vs_gpu_comparison/, accessed 2026-09-08]. Any 2B AR-TTS RTF claim for 125H CPU is UNVERIFIED.
- Practical CPU path is fp32 or WOQ-int8/int4 + `torch.compile`+SDPA, not naive bf16 on client CPU [Source: https://pytorch.org/blog/genai-acceleration-intel-xeon/, accessed 2026-09-08].

## 3. Windows on ARM64 (Snapdragon X Elite)

- Official native Arm64 PyTorch for Windows arrived with PT 2.7 for Python 3.12; CPU-only, no CUDA [Source: https://blogs.windows.com/windowsdeveloper/2025/04/23/pytorch-arm-native-builds-now-available-for-windows/, accessed 2026-09-08] [Source: https://learn.arm.com/install-guides/pytorch-woa/, accessed 2026-09-08].
- Install needs ARM64 Python, VS2022 ARM64/ARM64EC tools, Rust; nightly via `https://download.pytorch.org/whl/nightly/cpu` [Source: https://blogs.windows.com/windowsdeveloper/2025/04/23/pytorch-arm-native-builds-now-available-for-windows/, accessed 2026-09-08]. Pre-2.7 required source build with APL + `vcvarsall.bat arm64` [Source: https://github.com/pytorch/pytorch/wiki/Build-PyTorch-and-LibTorch-on-Windows-ARM64, accessed 2026-09-08].
- Unofficial native wheels add QNNPACK/XNNPACK + py3.11/3.12/3.13, CPU-only [Source: https://github.com/Snapdragon-AI-Stack/pytorch-arm64-wheels, accessed 2026-09-08].
- Independent 2026-07-13 X1E80100/64GB/Win11-25H2 test: official `2.12.1+cpu win_arm64` (cp311-only) was 2–3.5× slower than x86 wheel under Prism (4096² GEMM 2.88s vs 1.37s; train-loop 44.9s vs 13.0s/iter), bf16 GEMM never completed (>150s), build shows `BLAS=APL`, no XNNPACK, flat 1→12-thread scaling [Source: https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch, accessed 2026-09-08].
- Same report: Oryon has NEON but no SVE/SVE2/BF16-SIMD, so bf16 casts via fp32; WSL2 Linux-aarch64 (OpenBLAS+oneDNN+XNNPACK/QNNPACK) did 0.83s GEMM and 9.1s/iter bf16 with full `manylinux_aarch64` ecosystem [Source: https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch, accessed 2026-09-08].
- `pyarrow`-blocks-`datasets/trl` gap was closed July 2026 by community win_arm64 Arrow 25.0.0 build, but perf conclusion unchanged [Source: https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch, accessed 2026-09-08].
- Claim “16 GB typical for X Elite laptops” is UNVERIFIED in this research (no OEM survey sourced). Assume tight headroom for 4–8 GB model + OS + app; exact budget is UNVERIFIED.
- Takeaway: ship WSL2 or emulated-x86 fallback if you must support X Elite; native win_arm64 CPU for 2B bf16 AR-TTS is not production-ready in 2026 [Source: https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch, accessed 2026-09-08].

## 4. Lighter alternatives

- dots.tts family is 2B fully-continuous AR (semantic encoder + LLM + AR flow-matching head, 48kHz AudioVAE) [Source: https://huggingface.co/rednote-hilab/dots.tts-mf, accessed 2026-09-08].
- Checkpoints share backbone: `base` (NFE 10–32), `soar` (SCA, NFE 10, best SIM), `mf` MeanFlow student (NFE 4 recommended, CFG fused/no-op `guidance_scale`), `mf-2steps` (fixed NFE 2 sCM), `mf-1step` (fixed NFE 1, omit sampling opts) [Source: https://github.com/rednote-hilab/dots.tts, accessed 2026-09-08] [Source: https://huggingface.co/dots-studio/dots.tts-mf-1step, accessed 2026-09-08] [Source: https://huggingface.co/dots-studio/dots.tts-mf, accessed 2026-09-08].
- 1-step extends fixed-step training to single-step with refinements; multi-step quality not claimed [Source: https://huggingface.co/dots-studio/dots.tts-mf-1step, accessed 2026-09-08].
- Reported quality (Seed-TTS-Eval style WER/SIM): soar-NFE10 avg 2.95, mf-NFE4 2.94 (~2.5× fewer evals), mf-2steps 3.02, mf-1step 3.08 [Source: https://github.com/rednote-hilab/dots.tts, accessed 2026-09-08]. CPU latency for these on 125H/X-Elite is UNVERIFIED.
- Quantization: GPTFast-CPU uses WOQ W8A16/W4A16 (activations bf16, weights int8/4) to cut bandwidth bottleneck [Source: https://pytorch.org/blog/genai-acceleration-intel-xeon/, accessed 2026-09-08]; generic INT8 cuts memory/speed but risks quality without calibration/retraining (demo via TorchAO/X86-Inductor) [Source: https://chaimrand.medium.com/optimizing-pytorch-model-inference-on-cpu-ccd3aa5884ad, accessed 2026-09-08].
- OpenVINO/NNCF path offers INT4/FP8 weight compression, dynamic activation quantization, KV-cache `u8/u4/bf16/f16` tuning [Source: https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-optimum-intel.html, accessed 2026-09-08] [Source: https://github.com/openvinotoolkit/openvino/releases/tag/2026.3.0, accessed 2026-09-08].
- Quantized dots.tts WER/SIM + RTF after TorchAO/ONNX/OV conversion is UNVERIFIED (no public numbers found).
- Trade-off summary: NFE 4→1 cuts head evals ~4× with small WER regression (+0.14 avg); quantization cuts GB but needs per-checkpoint listening/SIM test [Source: https://github.com/rednote-hilab/dots.tts, accessed 2026-09-08].

## 5. DirectML / OpenVINO verdict for AR TTS

- `torch-directml` (PrivateUse1, DX12) supports only up to torch 2.3.1 per MS docs; install via `pip install torch-directml` [Source: https://learn.microsoft.com/en-us/windows/ai/directml/pytorch-windows, accessed 2026-09-08] [Source: https://pypi.org/project/torch-directml/, accessed 2026-09-08].
- Last preview was Aug 2024 (2.4.dev240815); op coverage is partial roadmap, not full ATen [Source: https://github.com/microsoft/DirectML/releases, accessed 2026-09-08] [Source: https://github.com/microsoft/DirectML/wiki/PyTorch-DirectML-Operator-Roadmap, accessed 2026-09-08].
- DirectML LLM sample runs Phi-2/Phi-3/Llama-2/Mistral via custom RoPE/MHA/MLP graphs in fp16/fp32 [Source: https://github.com/microsoft/DirectML/tree/master/PyTorch/llm, accessed 2026-09-08]. No dots.tts support evidenced → dead end for stock AR+flow TTS in 2026 is UNVERIFIED but likely without custom port.
- DirectML EP is in sustained engineering; MS directs new ONNX-Runtime Windows work to WinML (same ORT APIs, auto-EP selection), max ONNX opset 20 [Source: https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html, accessed 2026-09-08].
- OpenVINO runs CPU (x86/ARM), Intel iGPU/dGPU, NPU with GenAI LLM/embedding/ASR pipelines, speculative decoding, lazy loading, `torch.compile` backend [Source: https://github.com/openvinotoolkit/openvino, accessed 2026-09-08] [Source: https://github.com/openvinotoolkit/openvino/releases/tag/2026.3.0, accessed 2026-09-08] [Source: https://github.com/openvinotoolkit/openvino/releases/tag/2026.0.0, accessed 2026-09-08].
- Built-in TTS is narrow: `SpeechT5ForTextToSpeech` + `Kokoro-82M` only; optimum-intel implements encoder/decoder/postnet/vocoder split for SpeechT5 [Source: https://openvinotoolkit.github.io/openvino.genai/docs/supported-models/, accessed 2026-09-08] [Source: https://huggingface.co/docs/optimum-intel, accessed 2026-09-08 — see modeling_text2speech.py] [Source: https://github.com/huggingface/optimum-intel/blob/d4dd21a3/optimum/intel/openvino/modeling_text2speech.py, accessed 2026-09-08]. Note: second URL is index page; code file is primary evidence.
- Demos exist for SpeechT5/Kokoro TTS via GenAI/OVMS and OuteTTS-350M (LLaMA-arch) via `OVModelForCausalLM` [Source: https://openvinotoolkit.github.io/openvino.genai/docs/use-cases/speech-generation/, accessed 2026-09-08] [Source: https://docs.openvino.ai/2026/model-server/ovms_demos_audio.html, accessed 2026-09-08] [Source: https://docs.openvino.ai/2024/notebooks/outetts-text-to-speech-with-output.html, accessed 2026-09-08].
- Verdict: OpenVINO = viable CPU/iGPU optimization route in principle (esp. LLM backbone as CausalLM), but dots.tts-2B AR+flow head conversion is UNVERIFIED custom work; DirectML = avoid for new AR-TTS.

## Recommendation

- (a) 125H: prototype upstream-torch XPU eager + `mf-1step`/`mf-2steps` bf16/fp16, keep CPU fp32+`torch.compile` fallback; avoid IPEX pin and naive CPU-bf16 [Sources above, accessed 2026-09-08].
- (b) X-Elite: assume CPU-only fp32/Q8 + small NFE; prefer WSL2 or cloud/offline-packaged x64 path until win_arm64 math matures [Source: https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch, accessed 2026-09-08].
- All performance claims need on-device RTF measurement (tok/s, sec per 10s audio, peak RSS); no citable dots.tts CPU/XPU RTF found → UNVERIFIED.

## Sources

- https://intel.github.io/intel-extension-for-pytorch/xpu/2.6.10+xpu/tutorials/releases.html (accessed 2026-09-08)
- https://github.com/intel/intel-extension-for-pytorch/releases (accessed 2026-09-08)
- https://pytorch-extension.intel.com/installation?os=windows&package=pip&platform=gpu&version=v2.6.10%2Bxpu (accessed 2026-09-08)
- https://intel.github.io/intel-extension-for-pytorch/ (accessed 2026-09-08)
- https://pytorch.org/blog/unlocking-pt-2-6-intel/ (accessed 2026-09-08)
- https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/install_windows_gpu.md (accessed 2026-09-08)
- https://intel.github.io/intel-extension-for-pytorch/xpu/latest/tutorials/features/torch_compile_gpu.html (accessed 2026-09-08)
- https://github.com/pytorch/pytorch/issues/126719 (accessed 2026-09-08)
- https://github.com/intel/torch-xpu-ops/discussions/1265 (accessed 2026-09-08)
- https://intel.github.io/intel-extension-for-pytorch/xpu/2.3.110%2Bxpu/tutorials/features.html (accessed 2026-09-08)
- https://www.intel.com/content/www/us/en/products/sku/236848/intel-core-ultra-5-processor-125h-18m-cache-up-to-4-50-ghz/specifications.html (accessed 2026-09-08)
- https://www.notebookcheck.net/Intel-Core-Ultra-5-125H-Processor-Benchmarks-and-Specs.783325.0.html (accessed 2026-09-08)
- https://github.com/huggingface/transformers/issues/41867 (accessed 2026-09-08)
- https://pytorch.org/blog/genai-acceleration-intel-xeon/ (accessed 2026-09-08)
- https://pytorch.org/blog/empowering-pytorch-on-intel-xeon-scalable-processors-with-bfloat16/ (accessed 2026-09-08)
- https://qwen.readthedocs.io/en/v2.5/benchmark/speed_benchmark.html (accessed 2026-09-08)
- https://qwen.readthedocs.io/en/v1.5/benchmark/hf_infer.html (accessed 2026-09-08)
- https://www.reddit.com/r/LocalLLaMA/comments/1fq883g/qwen_25_cpu_vs_gpu_comparison/ (accessed 2026-09-08)
- https://chaimrand.medium.com/optimizing-pytorch-model-inference-on-cpu-ccd3aa5884ad (accessed 2026-09-08)
- https://blogs.windows.com/windowsdeveloper/2025/04/23/pytorch-arm-native-builds-now-available-for-windows/ (accessed 2026-09-08)
- https://learn.arm.com/install-guides/pytorch-woa/ (accessed 2026-09-08)
- https://github.com/pytorch/pytorch/wiki/Build-PyTorch-and-LibTorch-on-Windows-ARM64 (accessed 2026-09-08)
- https://github.com/Snapdragon-AI-Stack/pytorch-arm64-wheels (accessed 2026-09-08)
- https://github.laiyagushi.com/LucRoot/Windows_ARM64_PyTorch (accessed 2026-09-08)
- https://github.com/rednote-hilab/dots.tts (accessed 2026-09-08)
- https://huggingface.co/rednote-hilab/dots.tts-mf (accessed 2026-09-08)
- https://huggingface.co/dots-studio/dots.tts-mf-1step (accessed 2026-09-08)
- https://huggingface.co/dots-studio/dots.tts-mf (accessed 2026-09-08)
- https://learn.microsoft.com/en-us/windows/ai/directml/pytorch-windows (accessed 2026-09-08)
- https://pypi.org/project/torch-directml/ (accessed 2026-09-08)
- https://github.com/microsoft/DirectML/releases (accessed 2026-09-08)
- https://github.com/microsoft/DirectML/wiki/PyTorch-DirectML-Operator-Roadmap (accessed 2026-09-08)
- https://github.com/microsoft/DirectML/tree/master/PyTorch/llm (accessed 2026-09-08)
- https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html (accessed 2026-09-08)
- https://github.com/openvinotoolkit/openvino (accessed 2026-09-08)
- https://github.com/openvinotoolkit/openvino/releases/tag/2026.3.0 (accessed 2026-09-08)
- https://github.com/openvinotoolkit/openvino/releases/tag/2026.0.0 (accessed 2026-09-08)
- https://openvinotoolkit.github.io/openvino.genai/docs/supported-models/ (accessed 2026-09-08)
- https://github.com/huggingface/optimum-intel/blob/d4dd21a3/optimum/intel/openvino/modeling_text2speech.py (accessed 2026-09-08)
- https://openvinotoolkit.github.io/openvino.genai/docs/use-cases/speech-generation/ (accessed 2026-09-08)
- https://docs.openvino.ai/2026/model-server/ovms_demos_audio.html (accessed 2026-09-08)
- https://docs.openvino.ai/2024/notebooks/outetts-text-to-speech-with-output.html (accessed 2026-09-08)
- https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-optimum-intel.html (accessed 2026-09-08)
