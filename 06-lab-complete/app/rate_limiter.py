"""
Rate limiting (tiêu chí 7) — sliding window log trên Redis sorted set.

• Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây
• Vượt giới hạn → HTTP 429 kèm Retry-After
• State nằm trong Redis → mọi worker/instance dùng chung, còn nguyên sau restart

Toàn bộ thao tác ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE chạy trong MỘT Lua
script nên nguyên tử: nhiều worker cùng lúc không thể cùng "lọt" qua giới hạn.
Request bị chặn KHÔNG được ghi vào window (không tự kéo dài thời gian bị khoá).
"""
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

_SLIDING_WINDOW = r.register_script("""
local key    = KEYS[1]
local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, count, tostring(oldest[2])}
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window) + 1)
return {1, count + 1, '0'}
""")


def check_rate_limit(key: str) -> dict:
    """Raise 429 khi vượt giới hạn. Trả về thông tin còn lại để gắn header."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    allowed, count, oldest = _SLIDING_WINDOW(
        keys=[f"ratelimit:{key}"],
        args=[now, WINDOW_SECONDS, limit, f"{now:.6f}-{uuid.uuid4().hex[:8]}"],
    )
    if not int(allowed):
        retry_after = max(1, int(float(oldest) + WINDOW_SECONDS - now) + 1)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "window_seconds": WINDOW_SECONDS,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    return {"limit": limit, "remaining": max(0, limit - int(count))}
