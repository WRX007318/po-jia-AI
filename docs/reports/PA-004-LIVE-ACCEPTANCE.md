# PA-004 Live Acceptance (partial; local live evidence)

Date: 2026-11-27. Branch: `feat/pa-004-chat-continuity`. All raw conversations and SQLite databases remain under the local, ignored `.pa003-cache/` directory and are not committed.

## Hardware and inference service

- `nvidia-smi` reported NVIDIA GeForce RTX 3060, driver 621.40, 12,288 MiB VRAM.
- The active local service was `D:\PoJiaAI\runtime\llama-server.exe`, CUDA b12774, IQ3_S, context 4096, GPU layers 99, CPU MoE 23, 4 decode/batch threads, Q8 KV cache and Flash Attention. Only one model service was running on port 59871.
- During live generation, observed GPU memory was 9,618–9,655 MiB; Windows reported 7.0–7.5 GiB free physical RAM. This is an observed range, not a formal peak for all tasks.

## Automated regression

`python -m unittest discover -s tests -v`: 30 tests passed. Includes stream completion/truncation, durable draft recovery, bounded context preservation, duplicate-boundary detection, confirmed-memory correction history, versioned behavior settings/rollback, computer-tool path/approval/step-limit checks, model integrity, and worker persistence tests. `compileall` passed for app and tests.

## Live 20-turn conversation

`tests/run_pa004_live_acceptance.py` called the PR #2 `Runtime.chat` and `Store` paths against the live CUDA IQ3_S service and an isolated SQLite database. All 20 user/assistant turns completed (40 history messages), the fixed early marker `青松731` was recalled in turn 20, and the final history matched the completed responses. Total measured inference time was 489.2 seconds. **Passed** for application API and persistence; this was not a GUI-driven test.

## Live long-form generation

`tests/run_pa004_longform_acceptance.py` began a real Chinese article on local photo backup. The first body chunk ended with `finish_reason=length`; the implementation kept a durable draft and did not commit it as complete. We then resumed the same stored draft in bounded requests. Four 512-token continuation attempts ended at `length`, followed by a 1024-token request that also ended at `length`; a final 256-token request generated a closing paragraph and ended normally. SQLite then held one user message plus one completed assistant response, with a 4,060-character answer. Total observed generation time across these requests was about 951.6 seconds. One earlier section boundary had a one-character exact overlap; the new code detects longer repeated boundaries and leaves the draft incomplete rather than silently rewriting displayed text. **Passed for multi-request completion and persistence**, with the long runtime and length-limited intermediate responses recorded.

## Live interruption and recovery

`tests/run_pa004_interrupt_recovery.py` closed a live client stream after 240 visible characters, saved the cancelled draft, closed/reopened SQLite, and verified the exact checkpoint. A 512-token continuation returned visible text but ended at `length`; the harness preserved that continuation and requested a short closing segment. The 256-token closing segment ended normally. Final verification found exactly two history messages (one user, one assistant), no remaining draft, and an assistant answer beginning with the exact interrupted prefix. **Passed for client-stream interruption, durable checkpoint recovery, multi-request continuation, and single-commit history.**

Important limit: closing the HTTP client stream did not establish that llama-server immediately stopped decoding. The exact b12774 README documents `/v1/chat/completions/control` only for ending a reasoning block, and `/slots/{id}` save/restore/erase actions; it documents no general chat cancellation action. An upstream llama.cpp issue also records generation continuing after HTTP client disconnect. The UI Stop control therefore means “stop receiving/saving further stream content and preserve the draft”; backend cancellation latency and service-restart recovery remain unverified. The interruption harness exercises a SQLite close/reopen, not a full Windows app restart. Sources: [b12774 server API docs](https://github.com/ggml-org/llama.cpp/blob/171527522/tools/server/README.md#post-v1chatcompletionscontrol-control-a-running-chat-completion-in-real-time), [upstream disconnect cancellation issue](https://github.com/ggml-org/llama.cpp/issues/24496).

## Computer-operation Agent live checks

- Installed the pinned `pywinauto==0.6.9` UIA dependency for the workbench's Python 3.15 user environment; the project pin is in `requirements-windows.txt`.
- `tests/run_computer_agent_model_plan_smoke.py` called the live IQ3_S CUDA model with a JSON schema. The latest run returned the requested read-only `list_windows` plan in 20.258 seconds; schema validation succeeded and the bounded executor returned zero allowlisted windows.
- `tests/run_computer_agent_uia_smoke.py` launched a fresh Notepad window through the agent's one-time approval path, inspected the actual UIA tree, wrote and read back 30 characters through the Edit control, saved the exact text under an isolated temporary workspace, compared the file byte-for-character, then closed the exact test window and removed the temporary directory. Overwriting an existing workspace file creates a local backup before atomic replacement. **Passed** for this limited live UIA and workspace flow.
- The executor accepts one bounded step at a time, permits only app paths explicitly chosen for the current task, constrains file access to the user-selected workspace, validates unique UIA controls, and requires a one-use user ticket for writes, launch, clicks and text changes. It has no shell, network, account, transaction, security-challenge, or process-kill tool.

## Desktop verification and remaining scope

The desktop shortcut `C:\Users\Administrator\Desktop\破甲 AI.lnk` exists, and a Python 3.15 process with the window title `破甲 AI` was present. The window was minimized and the Computer Use helper reported it could not capture a minimized window; this run did **not** claim visual GUI acceptance or a fresh shortcut launch. Automatic startup after a cold boot, visual-model recognition on this PR #2 app session, and live testing of the new automatic-continuation/memory/behavior settings UI remain unverified.

Opt-in text-only auto-continuation is bounded to at most four additional 512-token requests and stops on non-length errors, user stop, or long exact overlap. It is off by default; image continuations are not automatically repeated. Long-term memory is explicit user-entered local data, bounded and query-matched, and corrections preserve the inactive prior version. The settings page now includes a versioned role/context editor with schema validation, atomic apply, invalid-file preservation, and rollback. These features have unit coverage, not a live GUI acceptance yet.

The single-step computer agent is an initial bounded implementation, not the full PA-004 workbench: task pause/continue/restart checkpoints, screenshot capture, richer before/after diagnostics, an explicitly approved test-command runner, multi-step model planning, and full permission/revocation editor remain incomplete. No external account action, security challenge handling, or unbounded shell access is implemented.

## Reproduction

With the authorized local model service ready, run:

```powershell
python -m unittest discover -s tests -v
python tests/run_pa004_live_acceptance.py <isolated-data-directory>
python tests/run_pa004_longform_acceptance.py <isolated-data-directory>
python tests/run_pa004_interrupt_recovery.py <isolated-data-directory>
python tests/run_computer_agent_model_plan_smoke.py
python tests/run_computer_agent_uia_smoke.py
```

Raw local result JSON, screenshots, conversation text, and SQLite files are intentionally excluded from the public repository.
