from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pa005_acceptance
from app.service_endpoint import service_base
from app.vision_pipeline import SCHEMA,_validate_schema,merge_ocr_text
from pa005_acceptance import compare_standard_ocr,enforce_duration,require_model


class JsonResponse:
    def __init__(self,payload):self.payload=payload;self.status=200
    def __enter__(self):return self
    def __exit__(self,*_):return False
    def read(self):
        import json
        return json.dumps(self.payload).encode()


class VisionAcceptanceGuardTests(unittest.TestCase):
    def test_annotation_schema_accepts_valid_and_rejects_bad_shapes(self):
        value={"page_type":"订单管理","visible_text":["订单列表"],"elements":[{"type":"table","text":"订单列表","label":"业务订单"}],"labels":["普通业务"],"needs_human_review":False}
        _validate_schema(value)
        for mutate in (
            lambda x:x.update(extra="unexpected"),
            lambda x:x.update(visible_text=["x"]*5),
            lambda x:x.update(needs_human_review=1),
            lambda x:x.update(elements=[{"type":"table","text":"x","label":"y","unexpected":1}]),
        ):
            invalid=dict(value);mutate(invalid)
            with self.assertRaisesRegex(ValueError,"Schema"):_validate_schema(invalid)
        self.assertEqual(SCHEMA["required"],list(value))

    def test_endpoint_port_is_configurable_and_loopback_only(self):
        with patch.dict(os.environ,{"POJIA_LLM_PORT":"61234","POJIA_LLM_HOST":"127.0.0.1"}):
            self.assertEqual(service_base(),"http://127.0.0.1:61234")
        with patch.dict(os.environ,{"POJIA_LLM_HOST":"0.0.0.0"}):
            with self.assertRaisesRegex(ValueError,"loopback"):service_base()
        with patch.dict(os.environ,{"POJIA_LLM_PORT":"70000"}):
            with self.assertRaisesRegex(ValueError,"TCP port"):service_base()

    def test_actual_model_gate_checks_full_path_not_just_basename(self):
        with tempfile.TemporaryDirectory() as td:
            model_dir=Path(td);expected=model_dir/"Inkling-2-Mini-Uncensored-AD-IQ2_M.gguf"
            with patch("app.bootstrap.MODEL_DIR",model_dir),patch("pa005_acceptance.urllib.request.urlopen",side_effect=[JsonResponse({"model_path":str(expected)}),JsonResponse({})]):
                self.assertTrue(require_model().endswith("IQ2_M.gguf"))
            wrongs=[model_dir/"Inkling-2-Mini-Uncensored-AD-IQ3_S.gguf",model_dir/"other"/expected.name]
            wrongs[1].parent.mkdir()
            for wrong in wrongs:
                with patch("app.bootstrap.MODEL_DIR",model_dir),patch("pa005_acceptance.urllib.request.urlopen",return_value=JsonResponse({"model_path":str(wrong)})):
                    with self.assertRaisesRegex(RuntimeError,"模型不匹配"):require_model()

    def test_standard_ocr_and_strict_twenty_second_performance_gate(self):
        compare_standard_ocr(" | ".join(pa005_acceptance.EXPECTED_OCR))
        with self.assertRaisesRegex(AssertionError,"PJ-2026-001"):
            compare_standard_ocr("业务订单管理 订单列表")
        with patch("pa005_acceptance.time.monotonic",return_value=21.999):
            self.assertEqual(enforce_duration(2.0),19.999)
        with patch("pa005_acceptance.time.monotonic",return_value=20.0):
            with self.assertRaisesRegex(TimeoutError,"超过 20 秒"):enforce_duration(0.0)

    def test_partial_local_ocr_does_not_hide_model_text(self):
        combined=merge_ocr_text("业务订单管理\n订单列表",["订单列表","PJ-2026-001 已完成","PJ-2026-002 处理中"])
        compare_standard_ocr(combined)
        self.assertEqual(combined.count("订单列表"),1)


if __name__=="__main__":unittest.main()
