"""Real local llama-server cancellation and slot-release probe; no private data."""
from __future__ import annotations
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime, IncompleteGeneration

HOME=Path(r"D:\PoJiaAI")
runtime=Runtime(HOME,HOME/"models"/"inkling2mini","iq3_s_cuda")
if runtime.status()!="ready":raise SystemExit("Expected current IQ3_S service is not ready; no task was submitted.")
with urllib.request.urlopen(runtime.base+"/slots",timeout=3) as response:slots=json.load(response)
if any(item.get("is_processing") for item in slots):raise SystemExit("Model slot is busy; refusing to interrupt another request.")
cancel=threading.Event();received=0;started=time.perf_counter();cancel_requested=None;observed="not_requested"
messages=[{"role":"user","content":"请连续输出一篇很长的中文说明，按编号列出许多互不重复的本地文件整理建议，每项都详细解释。"}]
stream=runtime.chat(messages,stream=True,max_tokens=2048,timeout=120,cancel_event=cancel)
try:
    for piece in stream:
        received+=len(piece)
        if received>=96:
            cancel_requested=time.monotonic();cancel.set();observed="http_stream_closed_after_visible_text";break
except IncompleteGeneration as exc:
    observed=exc.reason
finally:
    stream.close()
deadline=time.monotonic()+15
while time.monotonic()<deadline:
    try:
        with urllib.request.urlopen(runtime.base+"/slots",timeout=3) as response:after=json.load(response)
        if not any(item.get("is_processing") for item in after):break
    except Exception:pass
    time.sleep(.25)
else:raise SystemExit("Model slot did not become idle within 15 seconds after cancellation.")
with urllib.request.urlopen(runtime.base+"/health",timeout=3) as response:healthy=response.status==200
if not healthy or received<96:raise SystemExit("Cancellation lacked visible output or left the service unhealthy.")
print(json.dumps({"build":after[0].get("id"),"visible_characters_before_stop":received,
                  "cancel_outcome":observed,"elapsed_seconds":round(time.perf_counter()-started,3),
                  "cancel_to_idle_seconds":round(time.monotonic()-cancel_requested,3) if cancel_requested else None,
                  "slot_idle":True,"service_healthy":healthy},ensure_ascii=False))
