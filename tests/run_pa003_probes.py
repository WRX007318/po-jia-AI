"""Reproducible PA-003 probes against a running loopback llama-server.

This script deliberately does not import app/runtime.py: probes must measure the
server actually listening at --base-url and must not assume a model, backend,
quantization, or launch profile. Reports are written to a unique local path and
must not be committed if they contain machine-specific information.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = {
    "type": "object",
    "properties": {
        "page_type": {"type": "string"},
        "visible_text": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        "record_count": {"type": "integer"},
        "needs_human_review": {"type": "boolean"},
    },
    "required": ["page_type", "visible_text", "record_count", "needs_human_review"],
    "additionalProperties": False,
}


class ProbeTimeout(TimeoutError):
    def __init__(self, message: str, partial: dict[str, Any]):
        super().__init__(message)
        self.partial = partial


def validate_schema(value: Any, schema: dict[str, Any] = SCHEMA) -> tuple[bool, list[str]]:
    """Validate the small JSON schema used by PA-003 without optional packages."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return False, ["root must be an object"]
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            errors.append("missing required property: " + key)
    if schema.get("additionalProperties") is False:
        extras = sorted(set(value) - set(schema.get("properties", {})))
        if extras:
            errors.append("additional properties: " + ", ".join(extras))
    for key, spec in schema.get("properties", {}).items():
        if key not in value:
            continue
        item = value[key]
        kind = spec.get("type")
        if kind == "string" and not isinstance(item, str):
            errors.append(key + " must be a string")
        elif kind == "boolean" and not isinstance(item, bool):
            errors.append(key + " must be a boolean")
        elif kind == "integer" and (not isinstance(item, int) or isinstance(item, bool)):
            errors.append(key + " must be an integer")
        elif kind == "array":
            if not isinstance(item, list):
                errors.append(key + " must be an array")
            else:
                if len(item) > spec.get("maxItems", len(item)):
                    errors.append(key + " exceeds maxItems")
                if spec.get("items", {}).get("type") == "string" and not all(isinstance(x, str) for x in item):
                    errors.append(key + " items must be strings")
    return not errors, errors


def _get_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_server_metadata(base_url: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"base_url": base_url, "health": None, "props": None, "errors": []}
    try:
        metadata["health"] = _get_json(base_url.rstrip("/") + "/health")
    except Exception as exc:
        metadata["errors"].append("health: " + type(exc).__name__ + ": " + str(exc))
    try:
        props = _get_json(base_url.rstrip("/") + "/props")
        # Avoid persisting a full local path in the report.
        model_path = props.get("model_path")
        if model_path:
            props["model_path_basename"] = pathlib.Path(str(model_path).replace("\\", "/")).name
            props.pop("model_path", None)
        metadata["props"] = props
    except Exception as exc:
        metadata["errors"].append("props: " + type(exc).__name__ + ": " + str(exc))
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        metadata["nvidia_smi"] = {
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip()[:1000],
        }
    except Exception as exc:
        metadata["nvidia_smi"] = {"error": type(exc).__name__ + ": " + str(exc)}
    return metadata


def _cancel_slot(base_url: str) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/slots/0?action=cancel"
    try:
        request = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            return {"attempted": True, "http_status": response.status}
    except Exception as exc:
        return {"attempted": True, "error": type(exc).__name__ + ": " + str(exc)}


def _image_content(prompt: str, image_path: pathlib.Path) -> list[dict[str, Any]]:
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + encoded}},
    ]


def consume_sse(response: Any, started: float, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": "",
        "reasoning_content_chars": 0,
        "finish_reason": None,
        "usage": None,
        "timings": None,
        "first_content_seconds": None,
        "event_count": 0,
    }
    try:
        for raw_line in response:
            elapsed = time.perf_counter() - started
            if elapsed > timeout:
                raise ProbeTimeout("wall-clock probe deadline exceeded", result.copy())
            line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            if not data:
                continue
            event = json.loads(data)
            result["event_count"] += 1
            if event.get("usage"):
                result["usage"] = event["usage"]
            if event.get("timings"):
                result["timings"] = event["timings"]
            for choice in event.get("choices") or []:
                result["finish_reason"] = choice.get("finish_reason") or result["finish_reason"]
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or ""
                result["reasoning_content_chars"] += len(reasoning)
                piece = delta.get("content") or ""
                if isinstance(piece, list):
                    piece = "".join(x.get("text", "") for x in piece if isinstance(x, dict))
                if piece:
                    if result["first_content_seconds"] is None:
                        result["first_content_seconds"] = round(elapsed, 4)
                    result["content"] += str(piece)
    except (socket.timeout, TimeoutError) as exc:
        raise ProbeTimeout(str(exc) or "socket read timed out", result.copy()) from exc
    return result


def request_chat(
    base_url: str,
    messages: list[dict[str, Any]],
    *,
    timeout: float,
    max_tokens: int,
    json_schema: dict[str, Any] | None = None,
    image_path: pathlib.Path | None = None,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_messages = [dict(message) for message in messages]
    if image_path:
        if not image_path.is_file():
            raise FileNotFoundError(str(image_path))
        if not request_messages:
            raise ValueError("image probe requires at least one message")
        last = request_messages[-1]
        last["content"] = _image_content(str(last.get("content", "")), image_path)

    body: dict[str, Any] = {
        "model": "local",
        "messages": request_messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": chat_template_kwargs or {"reasoning_effort": "none"},
    }
    if json_schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "pa003_probe", "schema": json_schema, "strict": True},
        }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = consume_sse(response, started, timeout)
    except ProbeTimeout:
        raise
    except (socket.timeout, TimeoutError) as exc:
        raise ProbeTimeout(str(exc) or "request timed out", {
            "content": "", "reasoning_content_chars": 0, "finish_reason": None,
            "usage": None, "timings": None, "first_content_seconds": None, "event_count": 0,
        }) from exc
    result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    result["generation_tokens_per_second"] = None
    completion_tokens = (result.get("usage") or {}).get("completion_tokens")
    timings = result.get("timings") or {}
    predicted_n = timings.get("predicted_n")
    predicted_ms = timings.get("predicted_ms")
    if isinstance(predicted_n, (int, float)) and isinstance(predicted_ms, (int, float)) and predicted_ms > 0:
        result["generation_tokens_per_second"] = round(predicted_n * 1000 / predicted_ms, 3)
        result["generation_speed_source"] = "llama.cpp timings.predicted_n/predicted_ms"
    elif isinstance(completion_tokens, int) and result.get("first_content_seconds") is not None:
        generation_seconds = max(0.001, result["elapsed_seconds"] - result["first_content_seconds"])
        result["generation_tokens_per_second"] = round(completion_tokens / generation_seconds, 3)
        result["generation_speed_source"] = "client observed completion_tokens / post-first-content duration"
    else:
        result["generation_speed_source"] = "unavailable: server did not provide completion token count or timing"
    return result


def evaluate_probe(
    name: str,
    response: dict[str, Any],
    *,
    gate_seconds: float | None = None,
) -> dict[str, Any]:
    content = response.get("content") or ""
    finish = response.get("finish_reason")
    row: dict[str, Any] = {
        "name": name,
        "status": "returned",
        "elapsed_seconds": response.get("elapsed_seconds"),
        "first_content_seconds": response.get("first_content_seconds"),
        "finish_reason": finish,
        "usage": response.get("usage"),
        "timings": response.get("timings"),
        "generation_tokens_per_second": response.get("generation_tokens_per_second"),
        "generation_speed_source": response.get("generation_speed_source"),
        "answer_chars": len(content),
        "reasoning_content_chars": response.get("reasoning_content_chars", 0),
        "event_count": response.get("event_count", 0),
        "output": content,
        "truncated": finish == "length",
        "complete": finish == "stop" and bool(content.strip()),
        "gate_passed": False,
    }
    if gate_seconds is not None:
        row["gate_seconds"] = gate_seconds
        row["within_time_gate"] = isinstance(row["elapsed_seconds"], (int, float)) and row["elapsed_seconds"] < gate_seconds

    if name == "chinese_short_answer":
        speed = row["generation_tokens_per_second"]
        row["content_correct"] = "破甲 AI 推理性能测试通过" in content
        row["gate_passed"] = bool(row["complete"] and row["content_correct"] and isinstance(speed, (int, float)) and speed >= 8)
    elif name in ("structured_json", "synthetic_vision"):
        try:
            parsed = json.loads(content)
            row["parsed_json"] = parsed
            valid, errors = validate_schema(parsed)
            row["schema_valid"] = valid
            row["schema_errors"] = errors
            row["gate_passed"] = bool(row["complete"] and valid and row.get("within_time_gate"))
            if name == "synthetic_vision":
                visible = " ".join(parsed.get("visible_text", [])) if isinstance(parsed, dict) else ""
                correct = (
                    isinstance(parsed, dict)
                    and "订单" in parsed.get("page_type", "")
                    and "订单列表" in visible
                    and parsed.get("record_count") == 2
                    and parsed.get("needs_human_review") is False
                )
                row["content_correct"] = correct
                row["gate_passed"] = bool(row["gate_passed"] and correct)
        except (json.JSONDecodeError, TypeError):
            row["schema_valid"] = False
            row["schema_errors"] = ["output is not valid JSON"]
    else:
        row["content_correct"] = bool(content.strip())
        row["gate_passed"] = bool(row["complete"] and row["content_correct"])
        if gate_seconds is None:
            row["gate_seconds"] = None
    return row


def run_one(
    name: str,
    messages: list[dict[str, Any]],
    *,
    base_url: str,
    timeout: float,
    max_tokens: int,
    gate_seconds: float | None = None,
    json_schema: dict[str, Any] | None = None,
    image_path: pathlib.Path | None = None,
    chat_template_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = request_chat(
            base_url, messages, timeout=timeout, max_tokens=max_tokens,
            json_schema=json_schema, image_path=image_path,
            chat_template_kwargs=chat_template_kwargs,
        )
        row = evaluate_probe(name, response, gate_seconds=gate_seconds)
    except ProbeTimeout as exc:
        partial = exc.partial
        partial["elapsed_seconds"] = round(time.perf_counter() - started, 4)
        row = evaluate_probe(name, partial, gate_seconds=gate_seconds)
        row.update({"status": "timeout", "error": str(exc), "gate_passed": False})
        row["cancel"] = _cancel_slot(base_url)
    except Exception as exc:
        row = {
            "name": name, "status": "failed",
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "error": type(exc).__name__ + ": " + str(exc),
            "gate_passed": False,
        }
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:59871")
    parser.add_argument("--probe", choices=("all", "text", "reasoning", "json", "vision"), default="all")
    parser.add_argument("--vision-image", type=pathlib.Path, default=ROOT / "tests" / "fixtures" / "synthetic_business.png")
    parser.add_argument("--vision-timeout", type=float, default=20)
    parser.add_argument("--json-timeout", type=float, default=30)
    parser.add_argument("--text-timeout", type=float, default=180)
    parser.add_argument("--reasoning-timeout", type=float, default=90)
    parser.add_argument("--text-max-tokens", type=int, default=128)
    parser.add_argument("--json-max-tokens", type=int, default=512)
    parser.add_argument("--vision-max-tokens", type=int, default=256)
    parser.add_argument("--backend", default="unspecified")
    parser.add_argument("--build", default="unspecified")
    parser.add_argument("--quant", default="unspecified")
    parser.add_argument("--gpu-layers", type=int)
    parser.add_argument("--cpu-moe", type=int)
    parser.add_argument("--context", type=int)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--threads-batch", type=int)
    parser.add_argument("--kv-cache", default="unspecified")
    parser.add_argument("--flash-attention", default="unspecified")
    parser.add_argument("--mmproj-offload", choices=("yes", "no", "unknown"), default="unknown")
    parser.add_argument("--reasoning-budget-tokens", type=int)
    parser.add_argument("--server-command", default="", help="Optional exact launch command; keep report local and redact before sharing.")
    parser.add_argument("--output-dir", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = args.base_url.rstrip("/")
    metadata = collect_server_metadata(base_url)
    if metadata.get("health") is None:
        raise SystemExit("本地推理服务健康检查失败；未运行任何推理探针。")

    profile = {
        "backend": args.backend, "build": args.build, "quant": args.quant,
        "gpu_layers": args.gpu_layers, "cpu_moe": args.cpu_moe,
        "context": args.context, "threads": args.threads,
        "threads_batch": args.threads_batch, "kv_cache": args.kv_cache,
        "flash_attention": args.flash_attention, "mmproj_offload": args.mmproj_offload,
        "reasoning_budget_tokens": args.reasoning_budget_tokens,
        "server_command": args.server_command or "not supplied",
        "server_props": metadata.get("props"),
    }
    report: dict[str, Any] = {
        "schema_version": 2,
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "environment": metadata,
        "gates": {
            "text_generation_tokens_per_second": 8,
            "json_seconds": args.json_timeout,
            "vision_seconds": args.vision_timeout,
        },
        "tests": [],
    }

    if args.probe in ("all", "text"):
        report["tests"].append(run_one(
            "chinese_short_answer",
            [{"role": "user", "content": "请严格只输出以下字符串，不要增删或解释：破甲 AI 推理性能测试通过"}],
            base_url=base_url, timeout=args.text_timeout, max_tokens=args.text_max_tokens,
        ))
    if args.probe == "reasoning":
        messages = [{"role": "user", "content": "用中文简要解释 CPU、GPU 和 RAM 的区别，并给出一个实际例子。"}]
        variants = (
            ("api_effort_none", [], {"reasoning_effort": "none"}, 256),
            ("system_final_only", [{"role": "system", "content": "只输出最终答案，不输出分析过程或 reasoning。"}], {"reasoning_effort": "none"}, 256),
            ("max_tokens_512", [{"role": "system", "content": "只输出最终答案，不输出分析过程或 reasoning。"}], {"reasoning_effort": "none"}, 512),
        )
        for name, system_messages, options, token_limit in variants:
            report["tests"].append(run_one(
                name, system_messages + messages, base_url=base_url,
                timeout=args.reasoning_timeout, max_tokens=token_limit,
                chat_template_kwargs=options,
            ))
    if args.probe in ("all", "json"):
        report["tests"].append(run_one(
            "structured_json",
            [{"role": "user", "content": "分析一个普通中文订单列表页面。只输出 JSON，最多列出4条重要可见文本，并给记录条数；普通业务页 needs_human_review=false。"}],
            base_url=base_url, timeout=args.json_timeout,
            max_tokens=args.json_max_tokens, gate_seconds=args.json_timeout,
            json_schema=SCHEMA,
        ))
    if args.probe in ("all", "vision"):
        report["tests"].append(run_one(
            "synthetic_vision",
            [{"role": "user", "content": "识别这张虚构普通订单列表截图。只输出 JSON：页面类别、最多4条重要可见文字、记录条数、needs_human_review。普通业务页设 false；若发现验证码或安全验证则 true，不要描述挑战内容。"}],
            base_url=base_url, timeout=args.vision_timeout,
            max_tokens=args.vision_max_tokens, gate_seconds=args.vision_timeout,
            json_schema=SCHEMA, image_path=args.vision_image,
        ))

    output_dir = args.output_dir or pathlib.Path(os.environ.get("POJIA_HOME", r"D:\PoJiaAI")) / "logs" / "pa003" / "probes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ("pa003-" + report["run_id"] + ".json")
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("REPORT=" + str(output))
    print("GATES_PASSED=" + str(sum(1 for item in report["tests"] if item.get("gate_passed"))))
    print("GATES_TOTAL=" + str(len(report["tests"])))
    return 0 if report["tests"] and all(item.get("gate_passed") for item in report["tests"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
