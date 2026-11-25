"""
Production AI Agent — Part 6 Final Project

Chạy:  uvicorn app.main:app --workers 2
Kiểm tra:  python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import release, reserve, settle
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import MOCK_RESPONSES, ask as llm_ask

# Upper bound đầu ra của mock (cùng công thức token như trong /ask), dùng để giữ chỗ budget.
MAX_OUTPUT_TOKENS = max(len(t.split()) for v in MOCK_RESPONSES.values() for t in v) * 2


# ── Structured logging: mỗi dòng log của app là 1 JSON object ──────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        if record.exc_info and record.exc_info[0]:
            payload["exc_type"] = record.exc_info[0].__name__  # chỉ tên lỗi, không stack trace
        return json.dumps(payload, ensure_ascii=False, default=str)


logger = logging.getLogger("agent")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logger.handlers = [_handler]
logger.setLevel(logging.INFO)
logger.propagate = False


def log_event(event: str, **fields) -> None:
    """Ghi 1 dòng JSON. Không bao giờ truyền API key / secret vào đây."""
    logger.info(event, extra={"fields": {"event": event, **fields}})


# ── App & lifecycle ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, port=settings.port)
    yield
    # Graceful shutdown: uvicorn tự bắt SIGTERM, ngừng nhận kết nối mới, chờ request
    # đang chạy xong rồi mới chạy phần dưới đây. Không tự đăng ký signal handler để
    # khỏi vô tình ghi đè handler của uvicorn.
    log_event("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log_event(
            "request",
            method=request.method,
            path=request.url.path,
            status=status,
            ms=round((time.perf_counter() - start) * 1000, 1),
        )


# ── Xử lý lỗi: trả mã lỗi rõ ràng, không lộ stack trace ─────────────────────
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log_event("redis_error", error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Dependency unavailable"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log_event("unhandled_error", error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Health / readiness ──────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: process còn sống là 200, không phụ thuộc Redis."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: Redis không kết nối được → 503 để load balancer ngừng gửi traffic."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"status": "ready"}


# ── Endpoint chính ──────────────────────────────────────────────────────────
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    # Thứ tự: auth (Depends) → rate limit → giữ chỗ budget → LLM → đối soát chi phí
    check_rate_limit(api_key)
    input_tokens = max(1, len(body.question.split()) * 2)
    reservation = reserve(input_tokens, MAX_OUTPUT_TOKENS)  # nguyên tử; vượt budget → 402
    try:
        answer = llm_ask(body.question)
    except Exception:
        release(reservation)  # LLM lỗi → trả lại toàn bộ phần giữ chỗ
        raise
    output_tokens = max(1, len(answer.split()) * 2)
    cost = settle(reservation, input_tokens, output_tokens)
    log_event("ask", input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
