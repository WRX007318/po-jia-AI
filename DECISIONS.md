# PA-003 实施决策日志

## 2026-11-27 — Stage 0 baseline

- **证据：**RTX 3060 12 GiB、NVIDIA 512.15；可用 RAM 8.68 GiB（低于 16 GiB 提示线）；Vulkan llama.cpp b12774；唯一服务当前为 12 GPU 层 / 2048 context / 6 线程；GPU 可用 3264 MiB。
- **决策：**依任务书继续 stage 1，但保留桌面会话，不自动关闭任何应用；只运行一个 llama-server。开始每个模型候选前记录资源，若系统可用 RAM <3 GiB、GPU OOM 或启动失败，则停止并回退。
- **理由：**任务书明确允许低于 16 GiB 时继续 stage 1；当前桌面应用属于用户会话，不能擅自终止。模型服务的单实例约束可避免叠加显存与内存负载。
- **回滚：**PA-002 已知可运行参数为 Vulkan `-ngl 12 -c 2048 -t 6 -tb 6 --reasoning-budget 64`。出现资源门槛时停止候选，按此参数恢复 IQ3_S；不变更系统驱动。
- **原始证据：**仅本机 `D:\PoJiaAI\logs\pa003\baseline-20261127-101812.txt` 与 `server-help-20261127-101812.txt`。
