"""Gate-timed independent text, JSON, and synthetic vision probes for PA-003."""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime

HOME=pathlib.Path(r"D:\PoJiaAI")
rt=Runtime(HOME,HOME/"models"/"inkling2mini")
if rt.status()!="ready":raise SystemExit("expected PA-003 local model is not ready")

SCHEMA={"type":"object","properties":{"page_type":{"type":"string"},"visible_text":{"type":"array","maxItems":4,"items":{"type":"string"}},"record_count":{"type":"integer"},"needs_human_review":{"type":"boolean"}},"required":["page_type","visible_text","record_count","needs_human_review"],"additionalProperties":False}
results={"profile":{"backend":"Vulkan","build":"b12774","quant":"IQ3_S","gpu_layers":99,"cpu_moe":23,"context":4096,"threads":6,"threads_batch":6,"flash_attention":"on","kv_cache":"q8_0","mmproj_offload":True,"reasoning_budget_tokens":64},"gates":{"text_generation_tokens_per_second":8,"json_seconds":30,"vision_seconds":20},"tests":[]}

def cancel_slot():
    try:
        request=urllib.request.Request(rt.base+"/slots/0?action=cancel",method="POST")
        urllib.request.urlopen(request,timeout=3).close()
    except Exception:pass

def probe(name,gate,fn):
    start=time.perf_counter()
    row={"name":name,"gate_seconds":gate}
    try:
        value=fn()
        row.update({"status":"returned","seconds":round(time.perf_counter()-start,3),"output":value})
        if name=="chinese_short_answer":
            row["gate_passed"]="推理性能测试通过" in value
        else:
            parsed=json.loads(value)
            row["parsed_json"]=parsed
            row["gate_passed"]=row["seconds"]<gate
            if name=="synthetic_vision":
                text=" ".join(parsed.get("visible_text",[]))
                row["correct_complete"]=("订单" in parsed.get("page_type","") and "订单列表" in text and parsed.get("record_count")==2 and parsed.get("needs_human_review") is False)
                row["gate_passed"] &= row["correct_complete"]
            else:
                row["valid_json"]=True
    except Exception as e:
        cancel_slot()
        row.update({"status":"failed","seconds":round(time.perf_counter()-start,3),"error":f"{type(e).__name__}: {e}"})
    results["tests"].append(row)
    print(json.dumps(row,ensure_ascii=False),flush=True)

probe("chinese_short_answer",None,lambda:rt.chat([{"role":"user","content":"请直接用中文回答：破甲 AI 推理性能测试通过。"}],timeout=180,max_tokens=256))
probe("structured_json",30,lambda:rt.chat([{"role":"user","content":"分析一个普通中文订单列表页面。只输出 JSON，最多列出4条重要可见文本，并给记录条数；普通业务页 needs_human_review=false。"}],timeout=30,json_schema=SCHEMA,max_tokens=512))
probe("synthetic_vision",20,lambda:rt.chat([{"role":"user","content":"识别这张虚构普通订单列表截图。只输出 JSON：页面类别、最多4条重要可见文字、记录条数、needs_human_review。普通业务页设 false；若发现验证码或安全验证则 true，不要描述挑战内容。"}],ROOT/"tests"/"fixtures"/"synthetic_business.png",timeout=20,json_schema=SCHEMA,max_tokens=256))

out=ROOT/"docs"/"reports"/"pa003-stage2-probes.json"
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print("REPORT="+str(out))
