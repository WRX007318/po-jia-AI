# PA-003 Probe Tooling Repair

Date: 2026-11-27
Status: probe-tool code and CI regression checks updated; live Windows/GPU model measurements remain pending.

## What changed

- Replaced tests/run_pa003_probes.py so it talks directly to the configured loopback OpenAI-compatible endpoint. It no longer imports Runtime or references nonexistent ChatRequest, rt.config, or rt._request members.
- Removed hard-coded Vulkan / IQ3_S / GPU-layer / context claims. Backend, build, quantization, offload and launch profile are supplied by command-line arguments and default to "unspecified".
- Captures /health, /props, available nvidia-smi output, SSE finish reason, completion usage, timing fields, first visible answer content time, reasoning-content character count, timeout and partial output.
- Treats finish_reason=length, missing final answer, schema mismatch, incorrect synthetic visual recognition and failed time/speed gates as failures.
- Adds strict validation for the PA-003 JSON schema. JSON parsing alone is no longer sufficient.
- Writes each run to a unique local D:\PoJiaAI\logs\pa003\probes\pa003-<run-id>.json file using exclusive creation; it no longer overwrites the previous evidence file.
- Adds regression tests for schema validation, finish-reason truncation, speed/time gates, SSE usage parsing and partial-output preservation on timeout.
- Adds a GitHub Actions workflow for compile and unit regression checks.

## Commits

- Probe rewrite: 54ab4c86e395cc24ed62f9ff811b1726b9871147
- Probe tests: c2e18adfc3b740fced4c2c203bd7c428e62f9c93
- SSE fixture newline correction: 47e5884877ca49387a1239c7da22a6c08a586179
- CI workflow: 013e07068860dcf9e0bb5ea77d5b99ca0e82b64a

## Automated evidence

GitHub Actions workflow "PA-003 probe and worker tests" completed with conclusion success for workflow run:
https://github.com/WRX007318/po-jia-AI/actions/runs/45954854669

The workflow compiles app/ and tests/ with Python 3.11 and runs:
python -m unittest discover -s tests -p "test_*.py" -v

This CI result proves only the repository's compile and unit/regression checks on ubuntu-latest. It does not prove NVIDIA driver state, CUDA/Vulkan performance, local model inference, image recognition latency, Windows desktop interaction or PA-003 acceptance gates.

## Local execution

Example profile arguments must be filled from the actual running server and its launch command; do not copy guessed values:

    python tests\run_pa003_probes.py --probe all ^
      --backend <actual-backend> --build <actual-build> --quant <actual-quant> ^
      --gpu-layers <actual-ngl> --cpu-moe <actual-cpu-moe> ^
      --context <actual-context> --threads <actual-threads> ^
      --threads-batch <actual-threads-batch> --kv-cache <actual-kv-cache> ^
      --flash-attention <actual-fa-setting> --mmproj-offload <yes-or-no> ^
      --server-command "<actual-redacted-launch-command>"

Run reasoning variants separately with --probe reasoning. Preserve all generated local JSON files; only publish sanitized metadata and evidence that contains no private machine paths, identifiers or user data.

## Remaining work

1. Confirm the current NVIDIA driver with local nvidia-smi; user-reported 621.40 must not be substituted for measured output.
2. Verify CUDA runtime asset provenance and deployment; keep Vulkan rollback intact.
3. Run same-input CUDA/Vulkan comparison and IQ3_S/IQ2_M matrix on the actual Windows host.
4. Complete reasoning, JSON and synthetic vision tests. Current model-performance gates remain failed or unverified; no PA-003 acceptance is claimed.
5. Continue PA-004 implementation only against real application behavior and add unit/Windows integration tests. The current UI still sends a fixed 512-token streaming request and does not expose finish_reason to the user.
