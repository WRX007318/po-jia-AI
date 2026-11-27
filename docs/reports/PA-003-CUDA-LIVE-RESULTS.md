# PA-003 CUDA Live Results

Date: 2026-11-27. These are Windows-host live measurements against llama.cpp b12774 (`171527522`), NVIDIA Studio driver 621.40, RTX 3060 12GB. Model: existing IQ3_S and existing F16 mmproj. No model was re-downloaded. CUDA server used `-ngl 99 --n-cpu-moe 23 -fa on --cache-type-k q8_0 --cache-type-v q8_0 -c 2048 -np 1 -t 6 -tb 6 --jinja --reasoning off --reasoning-budget 64 --no-reasoning-preserve --metrics` on isolated port 59872. Vulkan install/runtime and backup were not changed.

| Probe | Result | Details |
|---|---|---|
| CUDA model load | Passed | `/health=ok`; `/props` reports same IQ3_S path and vision=true; idle GPU use about 9.1 GiB. |
| Chinese short answer | Content passed, speed gate failed | Correct phrase returned; 96 generation tokens, `finish_reason=stop`, 21.703s wall; llama.cpp generation 5.37 tok/s; first visible content 16.50s. Required >=8 tok/s. |
| Structured JSON | Passed | 26.89s (<30); strict schema valid; final stop. |
| Synthetic vision, 1024 long edge | Failed | 20.12s timeout; no complete result. |
| Synthetic vision, 768 long edge | Failed | 20.24s timeout; first visible content 15.41s; returned fragment was truncated/non-JSON. |

Local raw unique run records (not committed): `D:\PoJiaAI\logs\pa003\probes-cuda\pa003-20261127T071855Z-79192f5b.json` and `D:\PoJiaAI\logs\pa003\probes-cuda-768\pa003-20261127T072047Z-c8efb1f5.json`. The earlier 20-second vision cancellation endpoint returned HTTP 501, but the server health remained ok and the slot became idle. No result was counted as passed after a timeout.

Vulkan comparison uses the already committed stage-2 run: same IQ3_S generated 4.77 tok/s; CUDA reached 5.37 tok/s on this run, still below target. This is not yet a controlled repeated comparison; CUDA returned a different completion length and resource conditions vary. IQ2_M and the full context/thread/offload matrix remain outstanding. PA-003 acceptance is not claimed.
