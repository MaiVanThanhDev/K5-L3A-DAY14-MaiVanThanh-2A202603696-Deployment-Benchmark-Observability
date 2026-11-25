"""
Production AI Agent — Part 6 Final Project

  GET  /health  liveness  — luôn 200 khi process còn sống (kể cả Redis chết)
  GET  /ready   readiness — 200 khi Redis OK, 503 khi Redis mất hoặc đang shutdown
  POST /ask     X-API-Key → rate limit (Redis) → cost guard (Redis) → LLM

Chạy:  uvicorn app.main:app --workers 2
Kiểm tra:  python check_production_ready.py
"""
import json
import logging
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging — mỗi dòng log là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            entry["exc"] = "".join(traceback.format_exception(*record.exc_info))[-2000:]
        return json.dumps(entry, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]          # thay mọi handler cũ → không còn dòng log dạng text
    root.setLevel(settings.log_level)
    return logging.getLogger("agent")


logger = _setup_logging()


def log(event: str, level: int = logging.INFO, **fields):
    logger.log(level, event, extra={"fields": fields})


# ─────────────────────────────────────────────────────────
# Lifecycle + graceful shutdown
# ─────────────────────────────────────────────────────────
START_TIME = time.time()
STATE = {"ready": False, "in_flight": 0}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: KHÔNG bắt buộc Redis — container vẫn lên, /ready sẽ báo 503 tới khi Redis sẵn sàng
    STATE["ready"] = True
    log("startup", environment=settings.environment, version=settings.app_version,
        redis_ok=redis_healthy(), rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd, monthly_budget_usd=settings.monthly_budget_usd)
    yield
    # Shutdown: uvicorn đã nhận SIGTERM, ngừng nhận kết nối mới và chờ request đang chạy xong.
    # Tới đây: báo not-ready (load balancer ngừng gửi traffic), đợi nốt request còn sót, đóng Redis.
    STATE["ready"] = False
    log("shutdown_started", in_flight=STATE["in_flight"])
    deadline = time.time() + 5
    while STATE["in_flight"] > 0 and time.time() < deadline:
        time.sleep(0.05)
    try:
        r.close()
    except Exception:
        pass
    log("shutdown_complete", uptime_seconds=round(time.time() - START_TIME, 1))


app = FastAPI(title="Production AI Agent", version=settings.app_version, lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs",
              redoc_url=None)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log mỗi request thành 1 dòng JSON + đếm request đang xử lý."""
    STATE["in_flight"] += 1
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response
    finally:
        STATE["in_flight"] -= 1
        if request.url.path not in ("/health", "/ready"):
            log("request", method=request.method, path=request.url.path, status=status,
                ms=round((time.perf_counter() - started) * 1000, 1))


# ─────────────────────────────────────────────────────────
# Xử lý lỗi — mã lỗi rõ ràng, không lộ stack trace cho client
# ─────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"field": "body" if e.get("type") == "json_invalid"
               else ".".join(str(p) for p in e["loc"][1:]) or "body",
               "msg": e["msg"]}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "Invalid request", "details": errors})


@app.exception_handler(redis.RedisError)
async def redis_error(request: Request, exc: redis.RedisError):
    log("redis_unavailable", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, headers={"Retry-After": "5"},
                        content={"error": "Service temporarily unavailable (state store down)"})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc, extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/")
def root():
    return {"app": "Production AI Agent", "version": settings.app_version,
            "endpoints": ["GET /health", "GET /ready", "POST /ask (X-API-Key)"]}


@app.get("/health")
def health():
    """Liveness: process còn sống → 200. Không phụ thuộc Redis (Redis chết thì restart cũng vô ích)."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness: 200 khi nhận được traffic; 503 khi đang shutdown hoặc Redis không kết nối được."""
    if not STATE["ready"]:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "shutting down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unavailable"})
    return {"ready": True, "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, client: str = Depends(verify_api_key)):
    # 1. Rate limit theo API key (429)
    rate = check_rate_limit(client)
    # 2. Cost guard TRƯỚC khi gọi LLM (402)
    check_budget(client)
    # 3. Gọi LLM
    answer = llm_ask(body.question)
    # 4. Ghi nhận chi phí SAU khi gọi
    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens, client)
    log("ask", client=client, user_id=body.user_id, question_chars=len(body.question),
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)
    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "rate_limit_remaining": rate["remaining"],
        },
    }
