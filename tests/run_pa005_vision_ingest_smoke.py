"""Live visual worker OCR/annotation/dedup/human-review smoke using a synthetic fixture."""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from store import Store
from vision_worker import Worker

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
with tempfile.TemporaryDirectory(prefix="pa005-vision-ingest-") as td:
    temp=Path(td);source=temp/"authorized-synthetic-source";source.mkdir()
    shutil.copy2(fixture,source/"a.png");shutil.copy2(fixture,source/"b-duplicate.png")
    store=Store(temp/"worker-data");task_id=store.create_task(str(source),2)
    started=time.perf_counter();Worker(temp/"worker-data").run_task(store.task(task_id));elapsed=time.perf_counter()-started
    task=store.task(task_id);rows=store.samples()
    if task["status"]!="completed" or int(task["processed"])!=1:
        raise SystemExit(f"worker task did not complete the unique sample exactly once: {task['status']} / {task['processed']}")
    if len(rows)!=1 or not rows[0]["category"] or not rows[0]["ocr"]:
        raise SystemExit("visual annotation was not committed to the temporary database")
    store.update_sample(rows[0]["id"],"人工纠正类别",["人工复核"],True)
    reviewed=store.sample(rows[0]["id"])
    if reviewed["category"]!="人工纠正类别" or not reviewed["reviewed"]:
        raise SystemExit("human correction did not persist")
    with urllib.request.urlopen("http://127.0.0.1:59871/props",timeout=3) as r:props=json.load(r)
    with urllib.request.urlopen("http://127.0.0.1:59871/health",timeout=3) as r:healthy=r.status==200
    if not healthy:raise SystemExit("inference service became unhealthy")
    print(json.dumps({"task_completed":True,"unique_samples":len(rows),"processed_count":task["processed"],
                      "ocr_characters":len(reviewed["ocr"]),"human_correction_persisted":True,
                      "elapsed_seconds":round(elapsed,3),"model":Path(props.get("model_path","")).name,
                      "database":"temporary synthetic fixture"},ensure_ascii=False))
