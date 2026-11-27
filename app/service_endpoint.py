"""Shared loopback endpoint configuration for the model service."""
from __future__ import annotations

import os


def service_base() -> str:
    """Return a validated local HTTP base URL; callers may override the port."""
    host = os.environ.get("POJIA_LLM_HOST", "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("POJIA_LLM_HOST must remain loopback-only")
    try:
        port = int(os.environ.get("POJIA_LLM_PORT", "59871"))
    except ValueError as exc:
        raise ValueError("POJIA_LLM_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("POJIA_LLM_PORT is outside the TCP port range")
    return f"http://{host}:{port}"
