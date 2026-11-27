import json
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pa003_probes as probes


class FakeResponse:
    def __init__(self, lines):
        self.lines = iter(lines)

    def __iter__(self):
        return self

    def __next__(self):
        value = next(self.lines)
        if isinstance(value, BaseException):
            raise value
        return value


class PA003ProbeTests(unittest.TestCase):
    def test_schema_accepts_exact_expected_object(self):
        value = {
            "page_type": "订单列表",
            "visible_text": ["订单列表", "待付款"],
            "record_count": 2,
            "needs_human_review": False,
        }
        valid, errors = probes.validate_schema(value)
        self.assertTrue(valid, errors)

    def test_schema_rejects_extra_property_and_wrong_boolean(self):
        value = {
            "page_type": "订单列表",
            "visible_text": ["订单列表"],
            "record_count": 2,
            "needs_human_review": "false",
            "unexpected": 1,
        }
        valid, errors = probes.validate_schema(value)
        self.assertFalse(valid)
        self.assertGreaterEqual(len(errors), 2)

    def test_text_gate_requires_real_speed_and_complete_stop(self):
        response = {
            "content": "破甲 AI 推理性能测试通过",
            "finish_reason": "stop",
            "elapsed_seconds": 5.0,
            "first_content_seconds": 1.0,
            "usage": {"completion_tokens": 40},
            "timings": {"predicted_n": 40, "predicted_ms": 4000},
            "generation_tokens_per_second": 10.0,
            "generation_speed_source": "test fixture",
            "reasoning_content_chars": 0,
            "event_count": 3,
        }
        self.assertTrue(probes.evaluate_probe("chinese_short_answer", response)["gate_passed"])
        response["finish_reason"] = "length"
        self.assertFalse(probes.evaluate_probe("chinese_short_answer", response)["gate_passed"])

    def test_json_gate_requires_schema_finish_and_time(self):
        content = json.dumps({
            "page_type": "订单列表",
            "visible_text": ["订单列表", "待付款"],
            "record_count": 2,
            "needs_human_review": False,
        }, ensure_ascii=False)
        response = {
            "content": content,
            "finish_reason": "stop",
            "elapsed_seconds": 12.0,
            "first_content_seconds": 1.0,
            "usage": {"completion_tokens": 30},
            "timings": {"predicted_n": 30, "predicted_ms": 5000},
            "generation_tokens_per_second": 6.0,
            "generation_speed_source": "test fixture",
            "reasoning_content_chars": 0,
            "event_count": 4,
        }
        self.assertTrue(probes.evaluate_probe("structured_json", response, gate_seconds=30)["gate_passed"])
        response["finish_reason"] = "length"
        self.assertFalse(probes.evaluate_probe("structured_json", response, gate_seconds=30)["gate_passed"])
        response["finish_reason"] = "stop"
        response["elapsed_seconds"] = 30.0
        self.assertFalse(probes.evaluate_probe("structured_json", response, gate_seconds=30)["gate_passed"])

    def test_sse_captures_finish_usage_and_first_content_time(self):
        lines = [
            b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"completion_tokens":1}}\\n',
            b'data: [DONE]\\n',
        ]
        result = probes.consume_sse(FakeResponse(lines), probes.time.perf_counter(), 10)
        self.assertEqual(result["content"], "hello")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["usage"]["completion_tokens"], 1)
        self.assertIsNotNone(result["first_content_seconds"])

    def test_sse_timeout_preserves_partial_output(self):
        lines = [
            b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\\n',
            socket.timeout("read timed out"),
        ]
        with self.assertRaises(probes.ProbeTimeout) as caught:
            probes.consume_sse(FakeResponse(lines), probes.time.perf_counter(), 10)
        self.assertEqual(caught.exception.partial["content"], "partial")


if __name__ == "__main__":
    unittest.main()
