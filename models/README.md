# 模型资源索引

核查日期：2026-11-27。共九个独立 GGUF 仓库；重复的 9B 链接已合并。以下为来源页标示的许可及示例文件大小，不是实测内存需求，也不是完整的量化清单。候选分类仅按初步资源量级，不表示性能排名。全部为第三方衍生版本，部署前应核对固定 revision、完整文件清单、哈希、上游许可与运行时。

| ID | 模型 / 来源 | 页面许可标签 | 示例文件大小 | 兼容性备注 | 初筛 |
|---|---|---|---|---|---|
| 01 | [DeepSeek-V4.1-Flash-1017](https://huggingface.co/AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF) | MIT | IQ1_M 231 GB 总计（含 110 GB Engram） | Strata；模型卡明确说明独立 Engram 尚不受 llama.cpp 支持 | 大型研究 |
| 02 | [GLM-5.3](https://huggingface.co/huihui-ai/Huihui-GLM-5.3-abliterated-GGUF) | MIT | UD-IQ1_S 217 GB | 引擎兼容性待核验；页面参数摘要与文件大小口径需复核 | 大型研究 |
| 03 | [Inkling-2-Mini](https://huggingface.co/AtomicChat/Inkling-2-Mini-Uncensored-GGUF) | Apache-2.0 | IQ2_M 8.67 GB；IQ3_S 13.3 GB | inkling2_loop；核验具体引擎版本及视觉组件 | 候选 |
| 04 | [Qwen3.8-27B](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF) | Apache-2.0 | IQ2_XS 8.42 GB；TQ1_0 6.61 GB | qwen35；特殊量化及视觉组件需单独核验 | 候选 |
| 05 | [GLM-5.3-Flash](https://huggingface.co/huihui-ai/Huihui-GLM-5.3-Flash-abliterated-GGUF) | MIT | UD-IQ1_S 93.1 GB | glm5-next；引擎版本待核验 | 大型研究 |
| 06 | [Hy4-flash](https://huggingface.co/alesha-pro/Hy4-flash-Uncensored-GGUF) | Tencent Hy License | IQ2_XXS 114 GB | hy_v4_flash；视觉组件和运行时待核验 | 大型研究 |
| 07 | [DeepSeek-V4-Pro-Qwen3.5-9B](https://huggingface.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF) | Apache-2.0 | 待核对具体分片 | Qwen3.5 9B 蒸馏相关衍生模型；不是完整 DeepSeek V4 Pro | 候选 |
| 08 | [Gemma-4-31B-it-ARA](https://huggingface.co/mradermacher/gemma-4-31B-it-ARA-heretic-GGUF) | Apache-2.0 | Q2_K 12.0 GB；Q3_K_M 15.4 GB | 视觉 mmproj 另计；基础模型和衍生许可待核验 | 候选 |
| 09 | [Qwen3.8-Flash-Next-v2](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF) | Qwen Community 1.0 | UD-Q5_K_XL 158 GB；Q8_0 188 GB | MoE；GSQ/RCO 与 Strata 相关版本需核验 | 大型研究 |
