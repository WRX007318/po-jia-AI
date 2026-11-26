"""Run end-to-end inference probes against the local llama-server."""
from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
from runtime import Runtime

root=pathlib.Path(r"D:\PoJiaAI")
rt=Runtime(root,root/"models"/"inkling2mini")
if rt.status()!="ready":raise SystemExit("local model server is not ready")
results={"server":"ready","profile":{"backend":"Vulkan","build":"b12774","gpu_layers":12,"context":2048,"threads":6,"reasoning_effort":"none"},"tests":[]}

def probe(name, fn):
    start=time.perf_counter()
    try:
        value=fn()
        detail={"name":name,"seconds":round(time.perf_counter()-start,3),"status":"returned","output":value}
        if name in ("structured_json","image_recognition"):
            detail["parsed_json"]=json.loads(value)
        results["tests"].append(detail)
    except Exception as e:
        results["tests"].append({"name":name,"seconds":round(time.perf_counter()-start,3),"status":"failed","error":f"{type(e).__name__}: {e}"})

probe("chinese_dialogue",lambda:rt.chat([{"role":"user","content":"用中文直接回答，不要解释：破甲 AI 本地推理已连通。"}],max_tokens=256))
probe("code_generation",lambda:rt.chat([{"role":"user","content":"用 Python 写一个函数，返回列表中偶数的平方；只输出代码。"}],max_tokens=256))
schema={"type":"object","properties":{"page_type":{"type":"string"},"visible_text":{"type":"array","maxItems":4,"items":{"type":"string"}},"elements":{"type":"array","maxItems":2,"items":{"type":"object","properties":{"type":{"type":"string"},"text":{"type":"string"}},"required":["type","text"],"additionalProperties":False}},"needs_human_review":{"type":"boolean"}},"required":["page_type","visible_text","elements","needs_human_review"],"additionalProperties":False}
probe("structured_json",lambda:rt.chat([{"role":"user","content":"简短识别页面，只输出 JSON。"}],json_schema=schema,max_tokens=512))
probe("image_recognition",lambda:rt.chat([{"role":"user","content":"识别虚构普通业务列表截图；可见文字最多3条，只输出简短 JSON。"}],pathlib.Path(__file__).resolve().parent/"fixtures"/"synthetic_business.png",json_schema=schema,max_tokens=512))
out=pathlib.Path(__file__).resolve().parent.parent/"docs"/"reports"/"pa002-inference-smoke.json"
out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(results,ensure_ascii=False,indent=2))
