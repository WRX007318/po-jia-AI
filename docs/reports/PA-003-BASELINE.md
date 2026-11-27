# PA-003 阶段 0：本机硬件与运行时基线

采集时间：2026-11-27 10:18:12 +08:00
原始、未脱敏采集结果只保存在 `D:\PoJiaAI\logs\pa003\baseline-20261127-101812.txt`；`llama-server --help` 输出只保存在同目录。此仓库只保留脱敏汇总。

## 基线结果

- CPU：Intel Core i5-10400F，6 核 / 12 线程。
- 内存：32 GiB（系统报告 31.91 GiB）；采集时可用 8.68 GiB，低于任务书的 16 GiB 提示线。
- GPU：NVIDIA GeForce RTX 3060 12 GiB；驱动 512.15；采集时显存已用 8877 MiB、可用 3264 MiB。
- 唯一运行中的模型服务：llama.cpp `1.1.0-dev` build `12774`，commit `171527522`，Vulkan Windows x64；当前模型为 Inkling 2 Mini AD-IQ3_S，固定 Hub revision `82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2`，本地完整文件 SHA-256 `23a8e6792481b6f1d0ebad51399e9ee2a2c2be8525b09ed1ae6737811159f892`，mmproj SHA-256 `5a72e0b6e2bef13c3f455f4edb85df0c752b92ff76ab46af879eae088163efe6`。
- 采集时 llama-server 完整运行参数（敏感的绝对路径已脱敏）：`-ngl 12 -c 2048 -np 1 -t 6 -tb 6 --reasoning off --reasoning-budget 64 --no-reasoning-preserve --metrics`，包含视觉投影；进程工作集约 10.67 GiB。
- 桌面会话工作集前五项：llama-server 10.67 GiB、Codex 0.68 GiB、ChatGPT 0.68 GiB、ChatGPT 0.30 GiB、OpenCode 0.30 GiB。真实进程 PID、完整命令行只保留在本机原始日志。

## 决策

基线 RAM 可用值低于 16 GiB。按 PA-003 阶段 0 指令继续阶段 1；不自动关闭桌面程序，以免影响用户会话、守兔、WDA、YOY 或其他应用。每次候选配置只运行单个模型服务；一旦可用 RAM 低于 3 GiB、加载失败或 GPU OOM，立即停止候选并回退。阶段 1 前先停止现有 12/2048/6 服务，避免双模型争用。驱动保持 512.15，阶段 3 前不做任何驱动变更。

Exit code：基线脚本 0；`--version` 0；`--help` 0。
