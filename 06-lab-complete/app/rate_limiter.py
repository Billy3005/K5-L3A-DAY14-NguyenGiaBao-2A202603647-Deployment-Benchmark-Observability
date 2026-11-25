"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

State nằm trong Redis nên mọi worker / instance dùng chung và vẫn còn sau khi
restart agent. Mỗi request là một member duy nhất (timestamp + uuid) với score là
timestamp. Thêm trước rồi mới đếm trong cùng một MULTI để hai request đồng thời
không cùng lọt qua mức giới hạn; request bị từ chối thì được gỡ ra để không tự
kéo dài cửa sổ của chính nó.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    now = time.time()
    # Không lưu API key thô trong Redis, chỉ lưu bản băm rút gọn.
    rkey = "rl:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    member = f"{now}-{uuid.uuid4().hex}"

    pipe = r.pipeline()  # transaction=True mặc định → MULTI/EXEC
    pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)
    pipe.zadd(rkey, {member: now})
    pipe.zcard(rkey)
    pipe.expire(rkey, WINDOW_SECONDS)
    _, _, count, _ = pipe.execute()

    if count > settings.rate_limit_per_minute:
        r.zrem(rkey, member)
        oldest = r.zrange(rkey, 0, 0, withscores=True)
        retry_after = WINDOW_SECONDS
        if oldest:
            retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
