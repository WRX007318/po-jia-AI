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
from pa005_acceptance import new_run,require_model,write_report

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import vision_pipeline
import vision_worker
from store import Store

vision_pipeline.tesseract_ocr=lambda _path,**_kwargs:""
vision_worker.analyze=vision_pipeline.analyze
run_id,report=new_run("visual-scheduler")
record={"run_id":run_id,"test":"visual-scheduler","passed":False,"database":"isolated application Store"}
try:
    model=require_model()
    with tempfile.TemporaryDirectory(prefix="pa005-visual-worker-") as td:
        temp=Path(td);source=temp/"authorized-synthetic-source";source.mkdir()
        shutil.copy2(ROOT/"tests"/"fixtures"/"synthetic_business.png",source/"fixture.png")
        data=temp/"worker-data";store=Store(data);task_id=store.create_task(str(source),1)
        worker=vision_worker.Worker(data);thread_errors=[]
        def run_worker():
            try:worker.run_task(store.task(task_id))
            except BaseException as exc:thread_errors.append(f"{type(exc).__name__}: {exc}")
        thread=threading.Thread(target=run_worker,daemon=True);thread.start()

        from pa005_acceptance import endpoint
        def slot_busy():
            with urllib.request.urlopen(endpoint()+"/slots",timeout=3) as r:slots=json.load(r)
            return any(slot.get("is_processing") for slot in slots)
        def wait_for(predicate,seconds,message):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                if predicate():return
                time.sleep(.1)
            raise SystemExit(message)
        def control(action):worker.control.write_text(json.dumps({"action":action}),encoding="utf-8")

        deadline=time.monotonic()+45
        while time.monotonic()<deadline and not slot_busy() and thread.is_alive() and store.task(task_id)["status"] not in {"error","faulted","completed"}:
            time.sleep(.1)
        if not slot_busy():raise SystemExit(f"worker did not submit visual inference: task={dict(store.task(task_id))}, thread_errors={thread_errors}")
        control("pause")
        wait_for(lambda:store.task(task_id)["status"]=="paused",20,"worker did not pause after its active request was canceled")
        if slot_busy():raise SystemExit("model slot remained busy after worker pause")
        control("resume")
        deadline=time.monotonic()+20
        while time.monotonic()<deadline and not slot_busy() and thread.is_alive() and store.task(task_id)["status"] not in {"error","faulted","completed","stopped"}:
            time.sleep(.1)
        if not slot_busy():raise SystemExit(f"worker did not resume visual inference: task={dict(store.task(task_id))}, thread_errors={thread_errors}")
        control("stop")
        thread.join(30)
        if thread.is_alive():raise SystemExit("worker did not stop within 30 seconds")
        status=store.task(task_id)["status"]
        if status!="stopped" or slot_busy():raise SystemExit(f"unexpected stopped-task state: {status}")
        with urllib.request.urlopen(endpoint()+"/health",timeout=3) as r:healthy=r.status==200
        if not healthy:raise SystemExit("model service health failed after worker stop")
        record.update({"passed":True,"task_paused":True,"task_resumed":True,"task_stopped":True,"model_slot_idle":True,"service_healthy":healthy,"model":model})
except BaseException as exc:
    record.update({"error_type":type(exc).__name__,"error":str(exc)[:600]})
    raise
finally:
    write_report(report,record)
print(json.dumps({**record,"report":str(report)},ensure_ascii=False))
