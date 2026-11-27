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

## 2026-11-27 — Stage 2 engine parameters

- **实测参数：**`-ngl 99 --n-cpu-moe 23 --mmproj-offload -fa on --cache-type-k q8_0 --cache-type-v q8_0 -c 4096 -t 6 -tb 6 -np 1 --jinja --reasoning-budget 64`。模型服务启动正常，视觉投影上下文有 Vulkan compute buffer；KV buffer 合计 304 MiB。
- **结果：**短中文回答 4.77 tok/s，低于目标；JSON 超过30秒，图片超过20秒，两者均取消并记录失败。配置没有达到目标，不能用 4K/Q8 作为阶段验收完成理由。
- **决策：**保留该失败配置作为阶段 3 引擎比较基线；驱动/引擎切换需基于官方最低驱动要求、离线回滚材料和 PA-002 Vulkan 启动配置，升级不成功可恢复 Vulkan。
- **回滚：**保持 IQ3_S、本机 b12774 Vulkan；可回到 PA-002 12/2048/6，或阶段1目标显存参数 99/23/2048/6。
- **原始证据：**仅本机 `D:\PoJiaAI\logs\pa003\stage2-iq3s-ncmoe23-ctx4096-q8-fa.*.log`。

## 2026-11-27 — Stage 3 driver / CUDA evaluation (incomplete)

- **硬件兼容核验：**本机 Windows 10 Pro 22H2 (19045)、RTX 3060、驱动 512.15。llama.cpp b12774 提供 CUDA 12.4 Windows x64 运行时包；NVIDIA 官方 610.88 页面列出 Win10 64-bit 与 RTX 3060。CUDA 12.4 GA toolkit 对应 Windows driver 551.61；现有 512.15 不满足该 GA 要求。
- **回滚证据：**旧显示驱动 INF `oem24.inf` 已通过 `pnputil /export-driver` 导出至本机 `D:\PoJiaAI\drivers\pa003`（1,580,357,513 bytes）；INF 签名状态 Valid。Vulkan b12774 runtime 53 个文件复制至 `D:\PoJiaAI\runtime-vulkan-b12774-backup`，逐文件 SHA256 manifest 匹配；服务 EXE 与 `ggml-vulkan.dll` 哈希已保存在本机终端输出。
- **安装状态：**NVIDIA 610.88 官方安装包 979,651,304 bytes，SHA256 `576A90C6F6EEA47748DB1DEFCBCA1746C81FE4EB972F3132D30878778CEE0B09`，Authenticode Valid，Signer NVIDIA Corporation。启动 `-s -noreboot -noeula` 后仍弹出“NVIDIA 安装程序”界面且驱动仍报 512.15；需人工交互。未安装 CUDA build、未声称驱动升级成功，不重启。
- **安全决策：**不在此安装阶段的界面上进行自动确认、不触发重启。保留官方签名安装包、DriverStore 导出包和 b12774 Vulkan 备份；后续在人工完成安装并确认 `nvidia-smi` 版本变化后，再安装/验证 CUDA b12774。
- **后续风险：**启动使用 Vulkan 备份的单实例加载在当前后台状态下未完成模型初始化（10GiB working set、GPU 约1GiB、health 503）；已停止仅由本轮启动的 PID 24740。原 PA-002 和其它用户应用未停止。
- **原始证据：**本机 `D:\PoJiaAI\drivers\pa003`、`D:\PoJiaAI\runtime-vulkan-b12774-backup`、`D:\PoJiaAI\logs\pa003\stage4-vulkan-rsn.*.log`。

## 2026-11-27 — Stage 4/5 probe preparation (not accepted)

- **决策：**独立探针新增 `--probe` 选项，支持单独运行 text / reasoning / json / vision，并可传入 768px 图片；不得改 `app/` 业务代码。对照任务书 reasoning 参数顺序，并记录完整 backend content 与 `\n\n` 分隔符，而非仅隐藏或截断字符串。
- **验证：**`python -m py_compile tests/run_pa003_probes.py`、`--help` 和 `git diff --check` 成功；这些属于脚本检查，不是模型验收。由于驱动安装器要求人工交互、模型备用启动未就绪，Stage 4/5 的 PA-003 推理尚未重新实测，视觉/Reasoning 仍为待运行。
- **回滚：**探针更改独立于 `app/`；启动失败时停止唯一 PA-003 进程，保留 PA-002 运行时及原有应用。
