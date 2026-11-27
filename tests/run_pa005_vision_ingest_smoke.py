"""Live visual worker OCR/annotation/dedup/human-review smoke using a synthetic fixture."""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from pa005_acceptance import compare_standard_ocr,enforce_duration,new_run,require_model,write_report

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from store import Store
from vision_worker import Worker

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
run_id,report=new_run("vision-ingest")
record={"run_id":run_id,"test":"vision-ingest","passed":False,"database":"isolated temporary application Store"}
try:
 expected_model=require_model()
 with tempfile.TemporaryDirectory(prefix="pa005-vision-ingest-") as td:
    temp=Path(td);source=temp/"authorized-synthetic-source";source.mkdir()
    shutil.copy2(fixture,source/"a.png");shutil.copy2(fixture,source/"b-duplicate.png")
    data=temp/"worker-data";store=Store(data);task_id=store.create_task(str(source),2)
    started=time.perf_counter();Worker(data).run_task(store.task(task_id));elapsed=enforce_duration(started)
    task=store.task(task_id);rows=store.samples()
    if task["status"]!="completed" or int(task["processed"])!=1:
        raise SystemExit(f"worker task did not complete the unique sample exactly once: {task['status']} / {task['processed']}")
    if len(rows)!=1 or not rows[0]["category"] or not rows[0]["ocr"]:
        raise SystemExit("visual annotation was not committed to the temporary database")
    standard_text=rows[0]["ocr"]+" "+rows[0]["category"]+" "+rows[0]["labels"]
    record["standard_ocr_hits"]={item:item in standard_text for item in __import__("pa005_acceptance").EXPECTED_OCR}
    compare_standard_ocr(standard_text)
    store.update_sample(rows[0]["id"],"人工纠正类别",["人工复核"],True)
    reviewed=store.sample(rows[0]["id"])
    if reviewed["category"]!="人工纠正类别" or not reviewed["reviewed"]:
        raise SystemExit("human correction did not persist")
    reopened=Store(data);recovered=reopened.task(task_id);recovered_sample=reopened.sample(rows[0]["id"])
    if recovered["status"]!="completed" or recovered_sample["category"]!="人工纠正类别" or not recovered_sample["reviewed"]:raise SystemExit("数据库重启恢复校验失败")
    with urllib.request.urlopen(__import__("pa005_acceptance").endpoint()+"/props",timeout=3) as r:props=json.load(r)
    if Path(props.get("model_path","")).name!=expected_model:raise SystemExit("活动模型在视觉验收期间发生变化")
    with urllib.request.urlopen(__import__("pa005_acceptance").endpoint()+"/health",timeout=3) as r:healthy=r.status==200
    if not healthy:raise SystemExit("inference service became unhealthy")
    record.update({"passed":True,"task_completed":True,"unique_samples":len(rows),"processed_count":task["processed"],"ocr_characters":len(reviewed["ocr"]),"human_correction_persisted":True,"restart_recovery":True,"elapsed_seconds":round(elapsed,3),"model":expected_model})
except BaseException as exc:
    record.update({"error_type":type(exc).__name__,"error":str(exc)[:500]})
    raise
finally:
 write_report(report,record)
print(json.dumps({**record,"report":str(report)},ensure_ascii=False))
