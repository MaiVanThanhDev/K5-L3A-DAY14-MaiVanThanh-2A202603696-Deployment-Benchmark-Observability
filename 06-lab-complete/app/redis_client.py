"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

• Đọc REDIS_URL từ config
• Không ping lúc import → app vẫn khởi động được khi Redis chưa sẵn sàng
  (redis.from_url chỉ tạo connection pool, kết nối thật mở ở lệnh đầu tiên)
• Timeout ngắn để /ready và /ask không treo khi Redis chết
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=2.0,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    """True nếu PING Redis thành công, False nếu không kết nối được."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
