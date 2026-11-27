# PA-003 阶段 1：IQ3_S 显存 / RAM 整形

日期：2026-11-27；运行时：llama.cpp b12774 Vulkan，RTX 3060 12 GiB；IQ3_S SHA-256 `23a8e6792481b6f1d0ebad51399e9ee2a2c2be8525b09ed1ae6737811159f892`。

## 实测轮次

固定 `-ngl 99 -c 2048 -np 1 -t 6 -tb 6`，只改变 `--n-cpu-moe`。显存/RAM 为 Windows 系统级快照，不是进程独占归因。

| CPU MoE 层 | GPU used/free MiB | 可用 RAM | server 工作集 | 结果 |
|---:|---:|---:|---:|---|
| 8 | 11931 / 210 | 9.63 GiB | 9.37 GiB | 模型健康加载；显存远超目标上限，无推理，立即停止 |
| 16 | 11923 / 218 | 12.55 GiB | 6.57 GiB | 模型健康加载；仍远超上限，无推理，停止 |
| 24 | 9218 / 2923 | 15.54 GiB | 3.57 GiB | 模型健康加载；低于目标下限，无推理，停止 |
| 23，选中 | 空闲 9629 / 2512；推理后 9666 / 2475 | 空闲 15.26；推理后 8.90 GiB | 空闲 3.95；推理后 10.41 GiB | 显存位于 9500–10500 MiB；中文短答成功 |

`--n-cpu-moe=23` 实测：正确返回“是的，破甲 AI 推理性能测试通过。”；首 token（prompt eval）4.438 秒，生成 84 tokens / 17.151 秒 = **4.84 tok/s**；请求总时长 21.588 秒。未达到 8 tok/s 门槛，PA-003 总体验收不通过，阶段 7 IQ2_M 仍须执行。

Verbose 分配日志显示 48 transformer layers、128 experts；`offloaded 49/49 layers to GPU`，Vulkan0 权重 buffer 1645.96 MiB，CPU-mapped 权重 buffer 共 47 个分块、合计 11065.18 MiB，KV buffer 64+240 MiB，Vulkan 计算 buffer 5977.74 MiB，视觉投影 Vulkan 计算 buffer 98.80 MiB。系统显存数值包含桌面图形进程。

各轮原始日志留在本机 `D:\PoJiaAI\logs\pa003\stage1-*.log` / `.err.log`，不上传含绝对路径的原始命令行或 verbose 日志。
