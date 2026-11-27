"""Read-only tokenizer check against the active local llama.cpp model."""
from __future__ import annotations
import json
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime

HOME=Path(r"D:\PoJiaAI")
runtime=Runtime(HOME,HOME/"models"/"inkling2mini","iq3_s_cuda")
with urllib.request.urlopen(runtime.base+"/props",timeout=3) as response:props=json.load(response)
if Path(props.get("model_path","")).name!="Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf":
    raise SystemExit("Tokenizer smoke is intended for the currently loaded IQ3_S model; no inference was run.")
messages=[{"role":"system","content":"你是本地中文助手。"},{"role":"user","content":"请精确计算这段中文提示的 tokenizer token 数。"}]
count=runtime.count_tokens(messages)
selected=runtime.build_context(messages,token_budget=min(runtime.context_size-512,512))
if count<1 or runtime.count_tokens(selected)!=count:raise SystemExit("exact chat-token count mismatch")
print(json.dumps({"model":Path(props["model_path"]).name,"build":props.get("build_info"),
                  "context_tokens":count,"context_limit":props["default_generation_settings"]["n_ctx"],
                  "output_reserve_tokens":512,"inference_performed":False},ensure_ascii=False))
