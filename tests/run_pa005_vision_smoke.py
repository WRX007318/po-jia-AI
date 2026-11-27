"""Live vision pipeline smoke against a repository-owned synthetic page fixture."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from pa005_acceptance import compare_standard_ocr,enforce_duration,new_run,require_model,write_report

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from vision_pipeline import analyze

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
run_id,report=new_run("vision")
record={"run_id":run_id,"test":"vision","passed":False,"fixture":"synthetic_business.png"}
try:
    expected_model=require_model();started=time.perf_counter()
    result=analyze(fixture,timeout=20,lease_path=Path(__import__("os").environ.get("POJIA_DATA_DIR",r"D:\PoJiaAI\data"))/"inference.lock")
    elapsed=enforce_duration(started)
    text=" ".join([result["ocr"],*result["raw"]["visible_text"],result["page_type"]])
    compare_standard_ocr(text)
    if result["model"]!=expected_model:raise AssertionError("analyze结果模型与活动服务模型不符")
    if not any(e.get("type"," ").lower() in {"table","list","列表","表格"} for e in result["elements"]):raise AssertionError("页面结构未识别出表格或列表")
    gpu=subprocess.check_output(["nvidia-smi","--query-gpu=memory.used,memory.free,utilization.gpu","--format=csv,noheader"],text=True,timeout=5).strip()
    record.update({"passed":True,"model":expected_model,"elapsed_seconds":round(elapsed,3),"recognized_page_type":result["page_type"],"structured_elements":len(result["elements"]),"human_review":result["needs_human_review"],"gpu":gpu})
finally:
    write_report(report,record)
print(json.dumps({**record,"report":str(report)},ensure_ascii=False))
