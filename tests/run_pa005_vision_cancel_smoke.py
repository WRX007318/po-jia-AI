"""Cancel an owned live visual request and verify the shared slot is released."""
from __future__ import annotations
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
import vision_pipeline

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
vision_pipeline.tesseract_ocr=lambda _path:""  # isolate model cancellation from optional OCR startup
cancel=threading.Event();started=time.monotonic()
def stop_soon():time.sleep(2);cancel.set()
threading.Thread(target=stop_soon,daemon=True).start()
try:
    vision_pipeline.analyze(fixture,timeout=120,lease_path=Path(r"D:\PoJiaAI\data\inference.lock"),cancel_event=cancel)
except InterruptedError:
    pass
else:
    raise SystemExit("The visual request returned before the cancellation probe fired.")
elapsed=time.monotonic()-started
with urllib.request.urlopen("http://127.0.0.1:59871/slots",timeout=3) as response:slots=json.load(response)
with urllib.request.urlopen("http://127.0.0.1:59871/health",timeout=3) as response:healthy=response.status==200
with urllib.request.urlopen("http://127.0.0.1:59871/props",timeout=3) as response:props=json.load(response)
if any(slot.get("is_processing") for slot in slots) or not healthy:
    raise SystemExit("Canceled visual request did not release the slot or service health.")
print(json.dumps({"cancel_requested":cancel.is_set(),"slot_idle":True,"service_healthy":healthy,
                  "cancel_to_return_seconds":round(elapsed-2,3),"build":props.get("build_info"),
                  "model":Path(props.get("model_path","")).name},ensure_ascii=False))
