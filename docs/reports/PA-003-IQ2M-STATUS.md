# PA-003 IQ2_M and CUDA matrix status

Date: 2026-11-27. This is a progress record, not a PA-003 acceptance report.

## Verified before IQ2_M testing

- Hardware: GeForce RTX 3060, 12,288 MiB; NVIDIA Studio driver 621.40. An idle snapshot showed 22.08 GiB available RAM and 568 MiB used VRAM, with desktop GUI processes responsible for the visible GPU utilization.
- CUDA runtime: llama.cpp b12774, commit `171527522`, extracted to `D:\PoJiaAI\runtime-cuda12-b12774`; the Vulkan runtime remains in `D:\PoJiaAI\runtime-vulkan-b12774-backup` and the production runtime has not been replaced.
- Existing IQ3_S CUDA live results are recorded separately in `PA-003-CUDA-LIVE-RESULTS.md`: 5.37 tok/s (speed gate failed), strict JSON 26.89s (individual gate passed), 768px synthetic vision 20.24s (failed). Overall PA-003 remains incomplete.

## IQ2_M download

- Pinned Hugging Face revision: `82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2`.
- Expected size: 8,665,091,680 bytes. Trusted Hub LFS SHA256: `fca99d488bff5d401c8bc6b0110c5377c743f0ffb3a6d19c1ae4a3b9071fa2cd`.
- The existing partial file was resumed with HTTP byte ranges to avoid starting from zero. At the time of this progress update it was still downloading; it has not been length-checked, hashed, moved to its final name, or loaded. No IQ2_M inference result is claimed.

## Added measurement support

- `scripts/pa003-cuda-matrix.ps1` runs CUDA configurations serially, records pre-load and ready-state RAM/GPU snapshots, invokes `tests/run_pa003_probes.py`, preserves individual startup/probe failures, and stops only the PID it starts. It has passed PowerShell parser validation but has not yet run against IQ2_M.
- The live performance matrix and IQ2_M report remain pending model download, exact length verification, SHA256 verification, and actual runs. Do not treat this file as a completed matrix.
