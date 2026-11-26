# PA-002 核心推理部署与工程整改验收记录

日期：2026-11-27（本机）
分支：`feat/pa-001-local-workbench`，更新 PR #1。

## 已实测

- 硬件：Intel i5-10400F（6 核/12 线程）、32 GiB RAM、RTX 3060 12 GiB；NVIDIA 驱动 512.15（CUDA 11.6）。未改动驱动。采用 llama.cpp 官方 b12774 Windows Vulkan x64 构建，避免 CUDA/驱动升级风险。
- 模型已在 `D:\PoJiaAI\models\inkling2mini`，约 13.34 GB GGUF + 639 MB mmproj。没有重复下载。HF 固定 revision 的 tree API `lfs.oid` 与本地完整文件 SHA-256 一致；Xet Hash/Resolve ETag 是对象标识，不可当内容 SHA256。模型启动前逐块 SHA256 校验；缺文件/尺寸/hash 错误会阻止服务标记 ready。
- llama-server 确实加载模型及视觉投影，`/health` 返回 ok，`/props` 的模型路径与 vision modality 经过检查。实测 Vulkan 配置为 12 层卸载、2048 context、6 threads（本次进程命令行记录）；一次系统快照为显存已用 8567 MiB、可用 3574 MiB、Windows 可用 RAM 5.58 GiB、server 工作集 13.59 GiB。应用/浏览器等桌面负载在快照中，数值会随使用变化。
- 一次中文短答真实返回“已连通。”；推理日志观测 prompt eval 约 6.0 tokens/s，生成约 2.1–2.5 tokens/s。单次 244 token 请求约 107 秒，其中生成约 104 秒。该速度偏慢。
- 桌面快捷方式 `破甲 AI.lnk` 实际启动 `pythonw.exe`，原生窗口标题为“破甲 AI”。桌面入口及窗口启动通过；聊天长请求与完整 GUI 操作验收未通过。
- `python -m unittest discover -s tests -v`：4 项通过；本次修改的 Python 文件 `py_compile` 通过。
- 安全测试图为虚构合成的普通业务列表图片，不含真实账号/客户数据。

## 失败与未验收（不得视为 PA-002 完成）

本机模型生成 reasoning 段很长，模板的 `reasoning_effort=none` 未能稳定令其跳过。烟测中中文短答通过；代码生成拿到被长度限制截断的代码片段；结构化 JSON 请求超过 240 秒超时；图片识别请求超过 240 秒超时并被服务取消。不能据此宣称 JSON 或图片识别成功。视觉 Worker 任务持久化、哈希去重、mock 分析标注、检查点完成、暂停标记已有自动化测试；真实图片经视觉模型识别、审核及 SQLite 入库尚未端到端验收。

没有在本次完整验证 8/14/16 GPU layer、多个 context 与线程组合的性能矩阵，现有 12/2048/6 只是启动观测值，不能宣称为最优配置。没有使用未授权网页或处理安全验证页面。没有获取真实授权业务截图，所以未对大麦真实普通业务页执行识别。

## PA-002 工程整改

- 用固定 Hub revision 的可信 `lfs.oid` 内容 SHA256 修复 Xet ETag 误判，保留独立 Xet ID 元数据；已下载模型复用。
- 默认数据/运行目录统一指向 `D:\PoJiaAI`，支持 `POJIA_HOME` 覆盖；启动检查模型文件及 SHA256。
- 增加服务 `/props` 模型路径与视觉能力核验、非空最终回答保护、结构化 JSON 入口、Tk 流式回答。
- 增加独立本地视觉 Worker、单实例锁、JSON 控制文件、暂停/继续/停止、失败不越过错误检查点、SQLite 哈希去重、OCR/视觉 JSON 标注与人工复核标志。传统 Tesseract 为可选项；本机未安装时使用本地 VLM 路径。
- `launch.pyw` 将应用 `app` 目录加入导入路径，修复桌面快捷方式 GUI 启动问题。

## 后续阻塞项

优先应解决 Inkling 模板的推理预算/停止 token/模板兼容或更换可兼容的 llama.cpp build，并再重复文本、代码、JSON、图片真实验收；然后做性能矩阵和视觉 Worker 脱离 GUI 的真实 DB 端到端运行。当前 PA-002 不通过整体功能验收。
