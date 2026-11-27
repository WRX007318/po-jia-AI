"""Live worker pause/resume/stop against a repository-owned synthetic fixture."""
from __future__ import annotations
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import vision_pipeline
import vision_worker
from store import Store

vision_pipeline.tesseract_ocr=lambda _path:""
vision_worker.analyze=vision_pipeline.analyze
with tempfile.TemporaryDirectory(prefix="pa005-visual-worker-") as td:
    temp=Path(td);source=temp/"authorized-synthetic-source";source.mkdir()
    shutil.copy2(ROOT/"tests"/"fixtures"/"synthetic_business.png",source/"fixture.png")
    data=temp/"worker-data";store=Store(data);task_id=store.create_task(str(source),1)
    worker=vision_worker.Worker(data)
    thread=threading.Thread(target=worker.run_task,args=(store.task(task_id),),daemon=True);thread.start()

    def slot_busy():
        with urllib.request.urlopen("http://127.0.0.1:59871/slots",timeout=3) as r:slots=json.load(r)
        return any(slot.get("is_processing") for slot in slots)
    def wait_for(predicate,seconds,message):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.1)
        raise SystemExit(message)
    def control(action):worker.control.write_text(json.dumps({"action":action}),encoding="utf-8")

    wait_for(slot_busy,45,"worker did not submit its visual inference")
    control("pause")
    wait_for(lambda:store.task(task_id)["status"]=="paused",20,"worker did not pause after its active request was canceled")
    if slot_busy():raise SystemExit("model slot remained busy after worker pause")
    control("resume")
    wait_for(slot_busy,20,"worker did not resume visual inference")
    control("stop")
    thread.join(30)
    if thread.is_alive():raise SystemExit("worker did not stop within 30 seconds")
    status=store.task(task_id)["status"]
    if status!="stopped" or slot_busy():raise SystemExit(f"unexpected stopped-task state: {status}")
    with urllib.request.urlopen("http://127.0.0.1:59871/health",timeout=3) as r:healthy=r.status==200
    if not healthy:raise SystemExit("model service health failed after worker stop")
    print(json.dumps({"task_paused":True,"task_resumed":True,"task_stopped":True,
                      "model_slot_idle":True,"service_healthy":healthy,"database":"temporary synthetic fixture"},ensure_ascii=False))
