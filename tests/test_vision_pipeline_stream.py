from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from app.vision_pipeline import IncompleteVisualResponse,InferenceIsolationError,analyze,tesseract_ocr

FIXTURE=Path(__file__).resolve().parent/"fixtures"/"synthetic_business.png"
ANNOTATION={"page_type":"业务订单管理","visible_text":["订单列表"],"elements":[],"labels":["普通业务"],"needs_human_review":False}


class StreamResponse:
    def __init__(self,lines):self.lines=lines;self.closed=False
    def __iter__(self):return iter(self.lines)
    def close(self):self.closed=True


class JsonResponse:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def read(self):return json.dumps(self.value).encode()


def sse_response(finish="stop",include_done=True):
    content=json.dumps(ANNOTATION,ensure_ascii=False)
    lines=[f'data: {json.dumps({"choices":[{"delta":{"content":content},"finish_reason":finish}]})}\n'.encode()]
    if include_done:lines.append(b"data: [DONE]\n")
    return StreamResponse(lines)


class VisionStreamTests(unittest.TestCase):
    def test_ocr_subprocess_consumes_the_shared_deadline(self):
        with patch("app.vision_pipeline.shutil.which",return_value="tesseract"),patch("app.vision_pipeline.subprocess.run",side_effect=__import__("subprocess").TimeoutExpired("tesseract",.1)) as run:
            with self.assertRaisesRegex(TimeoutError,"OCR 超出"):
                tesseract_ocr(FIXTURE,timeout=.1)
            self.assertEqual(run.call_args.kwargs["timeout"],.1)

    def call_stream(self,response,slots=None,drain=.2):
        slots=slots or [{"is_processing":False}]
        with patch("app.vision_pipeline.tesseract_ocr",return_value=""),patch("app.vision_pipeline.urllib.request.urlopen",side_effect=[response,JsonResponse(slots),JsonResponse({"model_path":"D:/fixture/IQ2.gguf"})]):
            return analyze(FIXTURE,timeout=20,cancel_event=threading.Event(),slot_drain_timeout=drain)

    def test_complete_stream_requires_stop_and_done_marker(self):
        result=self.call_stream(sse_response())
        self.assertEqual(result["raw"],ANNOTATION)
        with self.assertRaisesRegex(IncompleteVisualResponse,"length"):
            self.call_stream(sse_response(finish="length"))
        with self.assertRaisesRegex(IncompleteVisualResponse,"DONE"):
            self.call_stream(sse_response(include_done=False))

    def test_slot_drain_is_bounded_and_surfaces_isolation(self):
        response=sse_response()
        def urlopen(url,*_args,**_kwargs):
            if hasattr(url,"full_url"):url=url.full_url
            if str(url).endswith("/slots"):return JsonResponse([{"is_processing":True}])
            return response
        with patch("app.vision_pipeline.tesseract_ocr",return_value=""),patch("app.vision_pipeline.urllib.request.urlopen",side_effect=urlopen),patch("app.vision_pipeline.time.sleep"):
            with self.assertRaisesRegex(InferenceIsolationError,"模型槽在 .* 秒内仍未确认空闲"):
                analyze(FIXTURE,timeout=20,cancel_event=threading.Event(),slot_drain_timeout=.05)


if __name__=="__main__":unittest.main()
