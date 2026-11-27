"""Shared safeguards for PA-005 live acceptance scripts."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
EXPECTED_MODEL=os.environ.get("POJIA_ACCEPTANCE_MODEL","Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf")
EXPECTED_OCR=("业务订单管理","订单列表","PJ-2026-001","PJ-2026-002","已完成","处理中")

def endpoint():
    from app.service_endpoint import service_base
    return service_base()

def require_model():
    with urllib.request.urlopen(endpoint()+"/props",timeout=3) as response:props=json.load(response)
    actual_path=Path(props.get("model_path","")).resolve()
    from app.bootstrap import MODEL_DIR
    expected_path=(Path(MODEL_DIR)/EXPECTED_MODEL).resolve()
    actual=actual_path.name
    if os.path.normcase(str(actual_path))!=os.path.normcase(str(expected_path)):
        raise RuntimeError(f"验收模型不匹配：要求 {expected_path}，服务实际加载 {actual_path}")
    with urllib.request.urlopen(endpoint()+"/health",timeout=3) as response:
        if response.status!=200:raise RuntimeError("实际推理服务健康检查失败")
    return actual

def new_run(name):
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:10]
    return run_id, ROOT/"docs"/"reports"/f"PA-005-{name}-{run_id}.json"

def write_report(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)

def compare_standard_ocr(text):
    missing=[item for item in EXPECTED_OCR if item not in text]
    if missing:raise AssertionError("标准 OCR 对照缺失："+", ".join(missing))

def enforce_duration(started):
    elapsed=time.monotonic()-started
    if elapsed>=20:raise TimeoutError(f"视觉耗时 {elapsed:.3f}s，超过 20 秒验收门槛")
    return elapsed
