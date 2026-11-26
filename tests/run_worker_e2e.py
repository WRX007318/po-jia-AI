"""Run the visual scheduler as a separate process against the synthetic fixture."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from store import Store

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
with tempfile.TemporaryDirectory(prefix="pojia-worker-e2e-",dir=ROOT/"tests") as td:
    base=pathlib.Path(td);source=base/"authorized-synthetic";source.mkdir()
    (source/fixture.name).write_bytes(fixture.read_bytes())
    db=base/"worker-data";store=Store(db);task_id=store.create_task(str(source),10)
    proc=subprocess.Popen([sys.executable,str(ROOT/"app"/"vision_worker.py"),"--data-dir",str(db)],cwd=ROOT/"app",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+420
        while time.monotonic()<deadline:
            task=store.task(task_id)
            if task["status"] in ("completed","error","waiting_model","stopped"):
                break
            time.sleep(1)
        task=store.task(task_id)
        row=store.samples()[0] if store.samples() else None
        result={"worker_process_exit":proc.poll(),"task_status":task["status"],"processed_unique_images":task["processed"],"checkpoint":task["checkpoint"],"error":task["error"],"sample":None if row is None else {"category":row["category"],"ocr":row["ocr"],"labels":row["labels"],"reviewed":row["reviewed"]}}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if task["status"]!="completed" or not row or not row["category"] or not row["ocr"]:
            raise SystemExit(1)
    finally:
        (db/"worker.json").write_text(json.dumps({"action":"stop_worker"}),encoding="utf-8")
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
