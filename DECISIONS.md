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

## 2026-11-27 — Driver update and safe inference follow-up

- **新状态证据：**随后本机 NVIDIA 安装完成；`nvidia-smi` 显示 610.88，设备 INF `oem30.inf`、DriverVersion `32.0.16.1088`，系统无需手动重启即可识别更新。未确认旧 512.15 是否仍可通过 Device Manager 回滚；原导出的 INF 与 Vulkan 备份仍在。
- **运行时资产：**b12774 release 链接的 CUDA 12.4 x64 ZIP HEAD 返回 200，长度 391,443,627；本地完整下载 SHA256 `8C79A9B226DE4B3CACFD1F83D24F962D0773BE79F1E7B75C6AF4DED7E32AE1D6`，ZIP 可列出 `cublas64_12.dll`、`cublasLt64_12.dll`、`cudart64_12.dll`。GitHub API 限流，尚无独立资产 SHA256 与上游对照；不能据本地哈希声称来源端校验完成。提取试验受后台负载影响中止，未保留不完整目录或改写生产 runtime。
- **Reasoning 实测：**原桌面启动的 PA-002 Vulkan 服务仍为 PID 15928/父进程 `launch.pyw`，未停止。直接流式请求传入 `chat_template_kwargs.reasoning_effort=none`，64-token 上限在 25.76s 完成但结束原因 `length`；仅收到 reasoning_content、final content 为空，reasoning 约 2.61 tok/s，判失败/截断。不是最终答案，不计通过。
- **资源/安全决策：**该用户窗口服务仍占 GPU 约8.4GiB、进程工作集约12GiB；不停止用户拥有的服务，也不并行装载测试模型。一个额外的由本轮启动的 b12774 Vulkan 加载实例曾停留在 health 503，随后仅停止该实例。Reasoning 对比、JSON/图像768px、CUDA 对比及完整阶段6–8矩阵仍未完成。
- **回滚：**生产服务未替换，生产 runtime 未动；CUDA 文件不部署。保留 `D:\PoJiaAI\runtime-vulkan-b12774-backup` 与旧 INF 导出。选择性验证需由用户先关闭桌面“破甲 AI”窗口，或另安排低负载维护时段；不得擅杀其进程。

## 2026-11-27 — CUDA live probes after user authorized service stop

- **驱动/进程：**现场 `nvidia-smi` 显示 RTX 3060 12GB / 621.40。桌面父窗口已不存在，但其 orphan `D:\PoJiaAI\runtime\llama-server.exe` PID 15928 仍持有 59871；仅在确认 PID、模型 IQ3_S、exe 和 listener 后按本轮用户授权停止该服务。PA-002 Vulkan runtime 本身未修改。
- **CUDA部署：**已复用本机下载的 b12774 `llama-b12774-bin-win-cuda-12.4-x64.zip` 和配套 cudart DLL，部署至独立 `D:\PoJiaAI\runtime-cuda12-b12774`。CUDA实例PID 24580/4988 在端口59872运行；未覆盖 Vulkan 安装。
- **实测：**CUDA same-model same-text 探针真实答案正确，96生成 token，`finish_reason=stop`，21.703s总时长、首内容16.50s、5.37 tok/s，速度门槛失败。CUDA结构化 JSON 26.89s、严格schema有效，通过该项。1024长边视觉20.12s超时；768长边视觉20.24s超时，结果截断、非JSON；不可记通过。原始运行JSON仅本机 `D:\PoJiaAI\logs\pa003\probes-cuda*`。
- **决策：**CUDA目前是IQ3_S更快的可运行候选，但5.37 tok/s仍低于8，尚非达标生产解；需同一测试输入多轮对照和IQ2_M。视觉超时取消接口返回501，health恢复且slot空闲；记录取消链路缺口。
- **未完成：**IQ2_M固定revision/LFS SHA256下载与测试、Reasoning变体、重复/受控CUDA-Vulkan比较、完整性能矩阵均待执行。PA-003总体验收不通过。
- **回滚：**CUDA实例仅监听59872且本轮已停止；生产路径和桌面runtime仍是原Vulkan b12774；需要回退时重启原桌面快捷方式即可。

## 2026-11-27 — IQ2_M download and matrix preparation

- **状态：**已核对 NVIDIA RTX 3060 / Studio 621.40；CUDA b12774 (`171527522`) 安装在独立 `D:\PoJiaAI\runtime-cuda12-b12774`，Vulkan runtime 与逐文件备份未更动。旧的 IQ3_S CUDA 探针为 5.37 tok/s（未达 8），JSON 26.89s（该单项通过），视觉 768px 20.24s（失败）。
- **IQ2_M：**固定 HF revision `82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2`，预期长度 8,665,091,680，权重 LFS SHA256 `fca99d488bff5d401c8bc6b0110c5377c743f0ffb3a6d19c1ae4a3b9071fa2cd`。使用 Range 续传到本机 `.part`；截至记录时约 2.17 GB，仍未完整、未计算最终 SHA、不得启动或称为已部署。
- **决策：**仅在下载长度和 LFS SHA-256 均验证后独立启动 IQ2_M 基准；桌面 `app/bootstrap.py` 仅校验 IQ3_S，因此 IQ2_M 不可冒名接入桌面 ready 判定。矩阵脚本按配置串行启停服务并写本机日志；CUDA/Vulkan 继续隔离。
- **回滚：**`D:\PoJiaAI\runtime-vulkan-b12774-backup` 保留原 53 文件 Vulkan 构建；生产 `runtime` 路径未修改。CUDA 与 IQ2_M 基准失败时停止自身进程并返回 Vulkan。

## 2026-11-27 — IQ2_M CUDA matrix result

- **完整性：**固定 HF revision 下载完成；大小 8,665,091,680 bytes，SHA256 与 Hub LFS OID `fca99d488bff5d401c8bc6b0110c5377c743f0ffb3a6d19c1ae4a3b9071fa2cd` 相符。CUDA llama.cpp b12774 `171527522` 实际加载同一文件并报告 vision=true。
- **矩阵：**串行完成 IQ2_M 全 GPU MoE 与 `--n-cpu-moe 23` 两组，各测 context 2048/4096/8192 × threads 4/6，共12格；每个推理期间500ms采样RAM/VRAM/GPU利用率。脱敏汇总在 `docs/reports/PA-003-PERF-REPORT.md`，原始JSON/CSV及server日志仅本机保留。
- **选择：**`-ngl 99 --n-cpu-moe 0 -c 4096 -t 4 -tb 4 -fa on -ctk q8_0 -ctv q8_0 --jinja -np 1`。严格提示复测：中文短答39.985 tok/s，结构化JSON3.588s，768px视觉5.854s，三项通过；VRAM峰值10,339 MiB，测试期间最低可用RAM13.28 GiB。全GPU 8192 context 峰值10,817–10,823 MiB，超过显存目标上限；CPU-MoE23 用显存6.61–7.52 GiB但速度6.35–8.14 tok/s且视觉6/6超时，淘汰。
- **限制：**llama-server props 将该已校验 Hub IQ2_M 文件报告为 `IQ2_XXS - 2.0625 bpw`，保留命名差异说明。生产桌面仍固定IQ3_S校验路径，IQ2_M仅独立基准；当前IQ3_S 5.37 tok/s旧结果不是同参数对照。视觉取消接口仍HTTP501；reasoning变体、桌面CUDA运行及PA-004连续对话/长文/GUI恢复未验收。
- **回滚：**所有IQ2测试服务只由矩阵脚本按PID启停；Vulkan运行时备份与生产路径未改，选中CUDA目录仍与生产目录隔离。
