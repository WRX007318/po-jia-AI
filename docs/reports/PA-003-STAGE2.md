# PA-003 阶段 2：引擎参数与三类推理探针

配置沿用 IQ3_S `-ngl 99 --n-cpu-moe 23 -t 6 -tb 6 -np 1`，追加 `--mmproj-offload -fa on --cache-type-k q8_0 --cache-type-v q8_0 -c 4096 --jinja`。当前 build `--help` 已核对这些参数有效；服务成功加载模型，健康端点正常。

## 真实结果

| 探针 | 结果 | 数据 |
|---|---|---|
| 中文短答 | 通过 | 正确回答；首 token 5.309 s；生成 84 tokens / 17.417 s = 4.77 tok/s；总时长 22.727 s |
| JSON Schema | 未通过 | 30.012 s 客户端超时；服务端截至取消生成 131 tokens，最终答案未完整返回、未解析 |
| 合成截图 VLM | 未通过 | 20.004 s 超时；取消时仍在视觉提示处理阶段（日志进度约 13%，n_tokens 638），没有最终答案 |

4K/Q8 参数后，服务端日志 KV buffer 为 Vulkan 64 + 240 MiB（合计 304 MiB）；Vulkan context compute buffer 5977.74 MiB，视觉投影上下文 Vulkan compute buffer 98.80 MiB。参数未触发加载异常。请求取消后 `/health` 仍返回 `ok`。

结束时系统快照：GPU used/free 9324/2817 MiB；可用 RAM 6.73 GiB；llama-server working set 12.84 GiB。与空载快照的差异包含已访问模型映射页和桌面负载。

原始启动日志及错误输出只保存在本机 `D:\PoJiaAI\logs\pa003\stage2-iq3s-ncmoe23-ctx4096-q8-fa.*.log`；机器路径不推送。可复现探针：`tests/run_pa003_probes.py`；脱敏数据：`docs/reports/pa003-stage2-probes.json`。两个失败门槛没有记为通过。
