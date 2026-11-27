# PA-003 Performance Report

Date: 2026-11-27. Windows 10 host, NVIDIA Studio driver 621.40, RTX 3060 12,288 MiB, 32 GiB RAM. This report records local model runs; it does not claim the PA-003 task is fully accepted.

## Conclusion

The best measured configuration is the verified Hugging Face file `Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf` on CUDA llama.cpp b12774, with all MoE weights on GPU (`-ngl 99`, `--n-cpu-moe 0`), context 4096, 4 generation/batch threads, Q8_0 K/V cache, Flash Attention enabled, one slot, and the existing F16 mmproj. A controlled rerun passed all three probe gates: exact Chinese short answer at 39.985 tok/s, strict JSON in 3.588 s, and synthetic 768px image recognition in 5.854 s. Peak measured VRAM was 10,339 MiB, within the requested 9,500–10,500 MiB range; minimum free system RAM during the run was 13.28 GiB.

IQ2_M meets the measured speed, JSON, vision, and VRAM gates at this profile. It is the preferred standalone CUDA candidate. The desktop application still validates and binds its production model path to IQ3_S; IQ2_M has not been integrated into that entry point. The model server reports GGUF `model_ftype` as `IQ2_XXS - 2.0625 bpw` even though the pinned Hub filename is `AD-IQ2_M`; the exact Hub file and LFS SHA were verified, and this metadata difference is disclosed rather than silently relabelled.

PA-003 remains incomplete because the IQ3_S comparison was not repeated as a controlled same-profile comparison, the server cancellation endpoint still returns HTTP 501 on visual timeouts, reasoning variants and desktop CUDA launch have not been live-verified, and the CUDA runtime has not yet been switched into the desktop production path.

## Evidence

The IQ2_M file was downloaded from pinned revision `82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2`. Verified length: 8,665,091,680 bytes. Verified SHA-256 (Hub LFS OID): `fca99d488bff5d401c8bc6b0110c5377c743f0ffb3a6d19c1ae4a3b9071fa2cd`. The matched mmproj remains the already verified F16 file. CUDA engine: llama.cpp b12774, commit `171527522`, CUDA 12.4 package in isolated `D:\PoJiaAI\runtime-cuda12-b12774`; Vulkan b12774 remains preserved under `D:\PoJiaAI\runtime-vulkan-b12774-backup`. No model weights, raw screenshots, raw chat histories, or raw machine logs are committed.

The matrix below contains 12 actual server runs. Every row used the same 768px synthetic ordinary order-list image and strict JSON schema. Each run sampled RAM and NVIDIA GPU memory/utilization every 500 ms. `text exact` records the probe's exact-output requirement; the initial matrix wording permitted the model to paraphrase the target phrase. The selected profile was subsequently rerun with a strict “output only this string” prompt and passed all gates.

| GPU profile | Context | Threads | Text tok/s / exact | JSON s | Vision s / gate | VRAM peak MiB | Minimum free RAM GiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| `-ngl 99`, `n-cpu-moe 0` | 2048 | 4 | 40.806 / no | 3.565 / pass | 6.191 / pass | 10,023 | 13.17 |
| `-ngl 99`, `n-cpu-moe 0` | 2048 | 6 | 40.795 / no | 3.552 / pass | 6.189 / pass | 10,077 | 13.08 |
| `-ngl 99`, `n-cpu-moe 0` | 4096 | 4 | 41.134 / yes | 3.463 / pass | 6.066 / pass | 10,359 | 13.11 |
| `-ngl 99`, `n-cpu-moe 0` | 4096 | 6 | 40.408 / no | 3.541 / pass | 5.885 / pass | 10,351 | 13.41 |
| `-ngl 99`, `n-cpu-moe 0` | 8192 | 4 | 39.672 / yes | 3.484 / pass | 6.075 / pass | 10,823 | 13.52 |
| `-ngl 99`, `n-cpu-moe 0` | 8192 | 6 | 40.343 / no | 3.559 / pass | 6.168 / pass | 10,817 | 13.48 |
| `-ngl 99`, `n-cpu-moe 23` | 2048 | 4 | 6.483 / no | 21.813 / pass | 20.249 / timeout | 6,727 | 13.36 |
| `-ngl 99`, `n-cpu-moe 23` | 2048 | 6 | 7.786 / yes | 19.057 / pass | 20.224 / timeout | 6,735 | 13.33 |
| `-ngl 99`, `n-cpu-moe 23` | 4096 | 4 | 6.558 / yes | 21.614 / pass | 20.147 / timeout | 7,058 | 13.43 |
| `-ngl 99`, `n-cpu-moe 23` | 4096 | 6 | 7.467 / no | 18.537 / pass | 20.163 / timeout | 7,084 | 13.48 |
| `-ngl 99`, `n-cpu-moe 23` | 8192 | 4 | 6.347 / no | 23.029 / pass | 20.183 / timeout | 7,504 | 13.42 |
| `-ngl 99`, `n-cpu-moe 23` | 8192 | 6 | 8.144 / yes | 17.888 / pass | 20.262 / timeout | 7,521 | 13.34 |

The selected-profile controlled rerun (IQ2_M, CUDA b12774, `-ngl 99`, `--n-cpu-moe 0`, context 4096, threads 4, Q8_0 K/V, Flash Attention) returned the exact Chinese target at 39.985 tok/s (2.542 s total, 2.309 s to first visible text), schema-valid JSON in 3.588 s, and a correct 2-record ordinary order-list recognition in 5.854 s. It passed 3/3 gates. The selected-profile 18-sample resource trace peaked at 10,339 MiB VRAM and 13.28 GiB free RAM.

The alternative `--n-cpu-moe 23` reduced VRAM use to 6.61–7.52 GiB but generated at 6.35–8.14 tok/s and timed out on all six visual probes. The all-GPU 8192-context rows used 10,817–10,823 MiB, above the requested maximum; they are excluded from the selected profile. At 4096 context, all-GPU rows measured 10,351–10,359 MiB and ~40 tok/s. Raw probe JSON, server logs, and resource CSV traces remain local under `D:\PoJiaAI\logs\pa003`; only this redacted summary is committed.

Previously recorded IQ3_S CUDA results remain in `PA-003-CUDA-LIVE-RESULTS.md`: 5.37 tok/s, JSON 26.89 s, and 768px visual timeout at 20.24 s. Those settings and runs are not a controlled IQ3_S vs IQ2_M comparison.

## Next steps

1. Keep IQ2_M as the standalone CUDA performance candidate and IQ3_S/Vulkan as the existing desktop rollback until a separate, explicit model-path integration is reviewed.
2. Implement or select a supported inference cancellation mechanism; `/slots/0?action=cancel` returned HTTP 501 on every timed-out visual request.
3. Run reasoning-variant probes and a controlled IQ3_S CUDA comparison using the selected context/thread/cache settings.
4. Switch the desktop runtime to the isolated CUDA build only after preserving the current runtime directory, then run the PR #2 desktop lifecycle against its supported IQ3_S model.
5. Keep long conversation, 20-turn continuity, long-form continuation, GUI interruption/restart, and history acceptance distinct from CI and standalone model probes.
