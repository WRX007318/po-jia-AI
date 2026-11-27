"""Live vision pipeline smoke against a repository-owned synthetic page fixture."""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from vision_pipeline import analyze

fixture=ROOT/"tests"/"fixtures"/"synthetic_business.png"
started=time.perf_counter()
result=analyze(fixture,timeout=90,lease_path=Path(r"D:\PoJiaAI\data\inference.lock"))
elapsed=time.perf_counter()-started
text=" ".join([result["ocr"],*result["raw"]["visible_text"],result["page_type"]])
if "订单列表" not in text or not result["elements"]:
    raise SystemExit("Vision smoke failed: fixture page title or structured controls were not recognized.")
gpu=subprocess.check_output(["nvidia-smi","--query-gpu=memory.used,memory.free,utilization.gpu","--format=csv,noheader"],text=True,timeout=5).strip()
print(json.dumps({"passed":True,"fixture":"synthetic_business.png","model":result["model"],
                  "elapsed_seconds":round(elapsed,3),"recognized_page_type":result["page_type"],
                  "structured_elements":len(result["elements"]),"human_review":result["needs_human_review"],
                  "gpu":gpu},ensure_ascii=False))
