"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

redis.from_url chỉ tạo client, KHÔNG kết nối ngay (kết nối xảy ra ở lệnh đầu tiên),
nên app vẫn khởi động được khi Redis chưa sẵn sàng. Timeout ngắn để /ready trả
503 nhanh thay vì treo khi Redis chết.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: không kết nối được Redis → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
