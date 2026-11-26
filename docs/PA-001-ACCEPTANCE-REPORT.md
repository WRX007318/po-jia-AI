# PA-001 本机验收记录（阶段性）

日期：2026-11-27（本机时区 Asia/Shanghai）  
范围：本机环境实测。未通过的项目明确标记，不以代码存在或服务进程存在冒充验收。

## 硬件与隔离

- CPU：Intel Core i5-10400F，6 核 / 12 线程。
- RAM：32 GiB，系统查询时可用约 19.4 GiB。
- GPU：NVIDIA GeForce RTX 3060 12 GiB；驱动 512.15，显示 CUDA 11.6；采样时空闲约 10.7 GiB。
- D 盘：初始可用约 305.5 GiB。模型存放在 `D:\PoJiaAI\models\inkling2mini`，运行时预留 `D:\PoJiaAI\runtime`，用户数据默认位于 `%USERPROFILE%\PoJiaAI\data`。
- 项目独立目录；没有修改守兔项目、系统 PATH、显卡驱动或全局 Python 包。

## 模型来源与完整性

- 来源：AtomicChat/Inkling-2-Mini-Uncensored-GGUF，固定 revision `82b34b9b0e5bc2e3e7b6d617ec8cc3e0f9692ee2`。
- 权重文件：`Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf`，13,340,510,176 字节。
- 视觉文件：`mmproj-Inkling-2-Mini-Uncensored-F16.gguf`，639,348,448 字节。
- 两个文件均已下载，实际 SHA256 分别为 `23a8e6792481b6f1d0ebad51399e9ee2a2c2be8525b09ed1ae6737811159f892` 与 `5a72e0b6e2bef13c3f455f4edb85df0c752b92ff76ab46af879eae088163efe6`。
- 固定 revision 的 HF tree API 仅返回 40 位对象 OID；Resolve ETag 为 Xet 对象标识，实测均不等于文件 SHA256。未找到该仓库在固定 revision 发布的独立 SHA256 manifest。文件大小匹配，但可信校验未通过，因此模型推理未启动；报告不把它标为已验证。应取得可信 SHA256 后再运行 `app/bootstrap.py` 的严格校验。
- llama.cpp v1.1.0 Release API 仅提供 `nightly-tag.txt`，没有可供本机直接下载安装的 Windows 二进制包。环境无 CMake/Visual Studio 编译链。CUDA 12.x 构建也不适合当前 512.15 驱动。运行时安装和真实推理待解决上述独立阻塞后完成。

## 已完成与测试结果

- 中文 Tk 桌面工作台及桌面快捷方式：`C:\Users\Administrator\Desktop\破甲 AI.lnk`。
- SQLite 会话持久化、截图 SHA256 去重、任务检查点、分类标签和人工审核队列。
- 独立视觉 worker 只读取用户明确选定的本地图片目录；暂停/继续/停止通过本机控制文件；不访问第三方网站，不处理安全验证页面。
- 编程工作台在用户选择目录后只读有限源码、过滤常见凭据目录，并提供新文件补丁预览/应用确认和回滚记录。命令执行未开放。
- 自动化测试：`python -m unittest discover -s tests -v`，4 项通过；Python 源码编译检查通过。
- UI 图形交互、快捷方式双击、worker 脱离 GUI 后存活、模型文本/图片推理尚未实测。没有真实截图数据，故样本准确率、延迟、显存峰值及并发数据未验证。

## 结论

阶段性实现可运行，但 PA-A、PA-E 的模型推理验收，以及 PA-B/PA-C/PA-D 的完整端到端人工验收仍未完成。当前缺少可信权重摘要、适配旧驱动的已核验 llama.cpp Windows 构建和完整 GUI 自动化运行环境；不得以此报告声称项目整体验收通过。
