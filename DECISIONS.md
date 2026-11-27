# PA-003 实施决策日志

## 2026-11-27 — Stage 0 baseline

- **证据：**RTX 3060 12 GiB、NVIDIA 512.15；可用 RAM 8.68 GiB（低于 16 GiB 提示线）；Vulkan llama.cpp b12774；唯一服务当前为 12 GPU 层 / 2048 context / 6 线程；GPU 可用 3264 MiB。
- **决策：**依任务书继续 stage 1，但保留桌面会话，不自动关闭任何应用；只运行一个 llama-server。开始每个模型候选前记录资源，若系统可用 RAM <3 GiB、GPU OOM 或启动失败，则停止并回退。
- **理由：**任务书明确允许低于 16 GiB 时继续 stage 1；当前桌面应用属于用户会话，不能擅自终止。模型服务的单实例约束可避免叠加显存与内存负载。
- **回滚：**PA-002 已知可运行参数为 Vulkan `-ngl 12 -c 2048 -t 6 -tb 6 --reasoning-budget 64`。出现资源门槛时停止候选，按此参数恢复 IQ3_S；不变更系统驱动。
- **原始证据：**仅本机 `D:\PoJiaAI\logs\pa003\baseline-20261127-101812.txt` 与 `server-help-20261127-101812.txt`。

## 2026-11-27 — Stage 1 IQ3_S memory shaping

- **参数核对：**build 12774 `--help` 确认 `--n-gpu-layers`、`--n-cpu-moe`、`--mmproj-offload`、`--flash-attn`、K/V cache type、threads-batch、Jinja 和 reasoning-budget 参数存在。`--mmproj-use-gpu` 不存在；阶段 2 使用官方 `--mmproj-offload`。
- **实测：**`-ngl 99 --n-cpu-moe 8` 与 16 显存约 11.9 GiB、空闲不足 220 MiB；不做推理并停止。`--n-cpu-moe 24` 显存 9218 MiB，不到下限。23 层空闲为 9629 MiB，短答后 9666 MiB，RAM 最低观测 8.90 GiB，中文短答通过，生成速度 4.84 tok/s。
- **决策：**在阶段 1 暂以 CPU MoE 23 作为可运行目标显存配置，进入阶段 2；它明确未达到 8 tok/s，阶段 7 IQ2_M 路径必须保留。首次 8 层因显存超上限，反向增加 CPU MoE 层数重测；理由是 GPU 只剩约 210 MiB，不安全且违反资源目标。`--fit` 对用户设置 `-ngl 99` 报告无法自动拟合，不依赖自动回调。
- **回滚：**阶段 2 若失败，停掉候选服务并回到 PA-002 `-ngl 12 -c 2048 -t 6 -tb 6 --reasoning-budget 64`；保留 Vulkan build、IQ3_S 和驱动。
- **原始证据：**`D:\PoJiaAI\logs\pa003\stage1-ncmoe{8,16,23,24}*.log` 及 err 日志；仅本机保存。
