# v2.0 — własny głos (dots.tts voice cloning): plan

Data: 2026-09-08. Research: `_bmad-output/research/dots-voice/` (3 digests + sources).

## Werdykt researchu (uczciwie)

- dots.tts (2B, Apache-2.0 kod + checkpointy, ~5,16 GB, BF16, torch>=2.8) to **CUDA-or-CPU**: CPU fallback to `float32` + `torch.set_num_threads(1)`, zero wsparcia XPU/DirectML/ONNX, zero wsparcia Windows (klasyfikatory tylko Linux/macOS).
- Jedyny publiczny datapoint CPU: ~RTF 60 (M1 Pro, nieoficjalny int4). Natywne XPU/Snapdragon dla dots.tts: UNVERIFIED.
- 125H iGPU: IPEX EOL marzec 2026 → docelowo upstream torch XPU; `torch.compile` na XPU/Windows beta; CPU 125H nie ma AVX-512/AMX (bf16 emulowane, ~26x wolniej niż fp32).
- Snapdragon X Elite: natywny torch win_arm64 CPU-only istnieje (2.7+), 2–3,5x wolniej niż emulacja, brak BF16 SIMD → fp32; 16 GB RAM ciasne na 8 GB wag fp32.
- Wniosek: **najpierw SPIKE pomiarowy na tym laptopie** (XPU eager bf16 vs CPU fp32, checkpoint mf-2steps/mf-1step, RTF + peak RSS). Bez liczb nie obiecujemy niczego. Fallbacki: Chatterbox (ma tryb CPU), Kokoro+OpenVINO (82M, lekki), Edge TTS (działa zawsze).

## Architektura (wpasowana w istniejący kod)

- `core/tts_providers.py`: port `synthesize(text, voice_id) -> wav bytes`; `EdgeTTSProvider` (obecne) + `DotsTTSProvider` (leniwy singleton jak ai-playground: `from_pretrained` raz, temp-wav na referencję, `generate(text, prompt_audio_path, prompt_text)`, seed).
- Voice store: `voices/<id>/{reference.wav, transcript.txt, meta.json}` + CRUD RPC (`addVoice`, `listVoices`, `testVoice` → podgląd WAV).
- Pipeline reuse bez zmian kształtu: `PartJob` + `voice/engine`; WAV 48kHz z dots → MP3 per part przez ffmpeg (już wymagany) albo WAV prosto do M4B.
- Checkpoint `dots.tts-mf-2steps` (NFE 2, ~5,16 GB): download na żądanie z progresem do user-data dir (NIE bundlowany w release).
- GUI: sekcja Voices (dodaj z pliku WAV + transkrypt + Test), Audiobook dostaje selektor głosu (Edge voices | custom), Settings: wybór checkpointu.
- Store: `ttsEngine: "edge" | "dots"`, `dotsCheckpoint`, `dotsVoiceId`.

## Etapy

1. **Spike (bez UI)**: venv-dots, `mf-2steps`, pomiar RTF/RAM na 125H (XPU vs CPU). Bramka GO/NO-GO.
2. Provider + voice store + RPC (testy offline z mockowanym runtime).
3. GUI Voices + selektor w Audiobook.
4. Bramka wydajnościowa na realnych rozdziałach (docelowo RTF audiobookowy do przyjęcia na nocne buildy).
5. Snapdragon: ten sam kod (torch win_arm64 CPU fp32), oznaczony experimental + fallback Edge; test na docelowym sprzęcie użytkownika.
6. Docs: przewodnik nagrywania referencji w GUI (8–12 s, patrz niżej).

## Nagrywanie głosu (dla użytkownika)

8–12 s bardzo czystej mowy, WAV, dokładna transkrypcja 1:1 (to ona stroi klonowanie), cichy pokój, mikrofon 15–20 cm, bez efektów, naturalna intonacja; kilka seedów do wyboru prozodii. Próbkę mogę zwalidować (czas, clipping, szum, sample rate) jak nagrasz.
