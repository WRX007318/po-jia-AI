# PA-004 Live Acceptance (partial)

Date: 2026-11-27. PR #2 branch `feat/pa-004-chat-continuity`, model IQ3_S with CUDA b12774, isolated SQLite data. This is real local model/application runtime and persistence evidence, not a UI acceptance claim.

## Automated regression

`python -m unittest tests.test_pa004_chat -v`: 7 tests passed. Covered stop-complete SSE, truncation, disconnect after visible content, reasoning-only empty final, reopen/complete once, session isolation/discard and duplicate/empty draft protections.

## Live 20-turn conversation

The acceptance script called the PR #2 `Runtime.chat` path and persisted every user/assistant turn through the PR #2 `Store` into an isolated SQLite database. Turn 1 completed with the sentinel “已记住”. Turn 2 ended with `IncompleteGeneration: 生成未完成（length）` after 22.113 seconds; no assistant final answer was committed for that turn and the run stopped. Result: 1 of 20 turns completed; 20-turn continuity and early-fact recall are **not passed**. The local run JSON and SQLite are not committed because they contain conversation content and local paths.

## Long text, interruption and history

Not completed in this run. The unit tests establish draft persistence/reopen/session isolation on temporary databases, but do not establish 2000-Chinese-character generation, real-model multi-request continuation, GUI behavior, or restart recovery during an actual long response. These remain unverified.

## Reproduction

After starting the authorized local CUDA/Vulkan model server on port 59871, run `python tests/run_pa004_live_acceptance.py <isolated-data-directory>`. Expected acceptance requires `turns_completed=20`, history equality, and marker recall; early model truncation is a failing run, not a pass.
