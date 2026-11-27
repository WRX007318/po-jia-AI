"""Live local-model planning followed by a read-only bounded Windows tool call."""
from __future__ import annotations
import json, os, tempfile, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from computer_agent import ComputerAgent
from runtime import Runtime

HOME=Path(r"D:\PoJiaAI");MODELS=HOME/"models"/"inkling2mini"
runtime=Runtime(HOME,MODELS)
if runtime.status()!="ready":raise SystemExit("verified IQ3_S CUDA service is not ready")
schema={"type":"object","properties":{"action":{"type":"string","enum":list(ComputerAgent.ACTION_ARGS)},
    "args":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},
    "app_id":{"type":"string"},"document":{"type":["string","null"]},"window_id":{"type":"integer"},
    "selector":{"type":"string"},"control_type":{"type":["string","null"]}},"additionalProperties":False}},
    "required":["action","args"],"additionalProperties":False}
messages=[{"role":"system","content":"提出一个 Windows Agent JSON 工具计划。只能读取：必须选择 list_windows，args 返回空对象。不调用 shell，不提出任何变更。"},
          {"role":"user","content":"检查本次允许的 Windows 应用窗口，只读。"}]
started=time.perf_counter();content=runtime.chat(messages,timeout=90,max_tokens=96,json_schema=schema)
elapsed=time.perf_counter()-started;plan=json.loads(content)
if plan!={"action":"list_windows","args":{}}:raise SystemExit("model plan did not match the read-only test request")
with tempfile.TemporaryDirectory(prefix="pojia-plan-smoke-") as td:
    agent=ComputerAgent(Path(td));agent.begin_task();approved_plan=agent.plan(plan["action"],plan["args"])
    result=agent.execute(approved_plan.id)
print(json.dumps({"model":"local IQ3_S CUDA","seconds":round(elapsed,3),"action":plan["action"],
                  "schema_valid":True,"tool_result_count":len(result),"steps":agent.steps},ensure_ascii=False))
