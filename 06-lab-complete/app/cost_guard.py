"""
Cost guard (tiêu chí 8).

• Cộng dồn chi phí LLM (tính theo token) vào Redis, theo từng API key
• Hai kỳ ngân sách, mỗi kỳ một key Redis tự hết hạn:
    cost:<client>:day:<YYYY-MM-DD>   so với DAILY_BUDGET_USD   (<= 0 → không giới hạn)
    cost:<client>:month:<YYYY-MM>    so với MONTHLY_BUDGET_USD (<= 0 → không giới hạn)
  Sang ngày / tháng mới → key mới → tự reset, không cần cron.
• Đã chi >= budget → HTTP 402 Payment Required, chặn TRƯỚC khi gọi LLM.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAY_TTL = 2 * 24 * 3600
_MONTH_TTL = 32 * 24 * 3600


def _keys(client: str) -> list[tuple[str, float, int, str]]:
    now = datetime.now(timezone.utc)
    return [
        (f"cost:{client}:day:{now:%Y-%m-%d}", settings.daily_budget_usd, _DAY_TTL, "daily"),
        (f"cost:{client}:month:{now:%Y-%m}", settings.monthly_budget_usd, _MONTH_TTL, "monthly"),
    ]


def estimate_tokens(text: str) -> int:
    """Ước lượng token thô (~4 ký tự / token) — đủ cho mock LLM."""
    return max(1, len(text) // 4)


def check_budget(client: str = "global") -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    keys = _keys(client)
    spent_values = r.mget([k for k, *_ in keys])
    for (key, budget, _, period), spent in zip(keys, spent_values):
        spent = float(spent or 0)
        if budget > 0 and spent >= budget:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": f"{period.capitalize()} budget exceeded",
                    "spent_usd": round(spent, 6),
                    "budget_usd": budget,
                    "period": period,
                },
            )


def record_cost(input_tokens: int, output_tokens: int, client: str = "global") -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    pipe = r.pipeline(transaction=True)
    for key, _, ttl, _ in _keys(client):
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, ttl)
    pipe.execute()
    return round(cost, 8)
