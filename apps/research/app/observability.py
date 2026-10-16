"""统一 JSON 日志与 X-Trace-Id 上下文（与网关/编排层字段对齐）。"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

TRACE_HEADER = "x-trace-id"
SERVICE = "research"

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def current_trace_id() -> str:
    return trace_id_ctx.get()


def trace_headers() -> dict[str, str]:
    tid = current_trace_id()
    return {TRACE_HEADER: tid} if tid else {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": SERVICE,
            "msg": record.getMessage(),
        }
        tid = current_trace_id()
        if tid:
            payload["traceId"] = tid
        for key in ("method", "path", "status", "latencyMs", "error"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = (request.headers.get(TRACE_HEADER) or "").strip()
        trace_id = incoming or str(uuid.uuid4())
        token = trace_id_ctx.set(trace_id)
        started = time.perf_counter()
        logger = logging.getLogger("equitylab.research")
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "latencyMs": latency_ms,
                },
            )
            return response
        except Exception as exc:
            logger.error("request failed", extra={"error": str(exc)})
            raise
        finally:
            trace_id_ctx.reset(token)
