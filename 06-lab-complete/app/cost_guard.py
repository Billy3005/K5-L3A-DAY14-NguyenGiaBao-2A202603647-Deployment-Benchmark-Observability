"""
Cost guard (tiêu chí 8).

Budget được GIỮ CHỖ nguyên tử trong Redis (Lua) TRƯỚC khi gọi LLM, nên nhiều request
đồng thời không cùng lọt qua budget. Sau khi xong thì đối soát phí thật; LLM lỗi thì
trả lại toàn bộ. Key mang ngày UTC lúc giữ chỗ và nằm trong Reservation, nên đối soát
và hoàn trả luôn vào đúng kỳ, kể cả khi request kéo qua nửa đêm UTC.
Đây là budget toàn cục của dịch vụ, không phải theo từng user.
"""
from datetime import datetime, timezone
from typing import NamedTuple

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
TTL_SECONDS = 2 * 24 * 3600

# KEYS[1]=key, ARGV[1]=phí giữ chỗ, ARGV[2]=budget, ARGV[3]=ttl. Trả 1 nếu giữ được, 0 nếu vượt budget.
_RESERVE = """
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
if spent + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return 0 end
redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""


class Reservation(NamedTuple):
    key: str
    amount: float


def _cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K


def _adjust(key: str, delta: float) -> None:
    pipe = r.pipeline()
    pipe.incrbyfloat(key, delta)
    pipe.expire(key, TTL_SECONDS)
    pipe.execute()


def reserve(input_tokens: int, max_output_tokens: int) -> Reservation:
    """Gọi TRƯỚC khi gọi LLM. Vượt budget → raise HTTPException(status_code=402)."""
    key = "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    amount = _cost(input_tokens, max_output_tokens)
    if not r.eval(_RESERVE, 1, key, amount, settings.daily_budget_usd, TTL_SECONDS):
        raise HTTPException(status_code=402, detail="Daily budget exceeded")
    return Reservation(key, amount)


def settle(res: Reservation, input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi LLM xong: đối soát phí thật với phần đã giữ, trả về phí thật."""
    actual = _cost(input_tokens, output_tokens)
    _adjust(res.key, actual - res.amount)
    return actual


def release(res: Reservation) -> None:
    """LLM lỗi: trả lại toàn bộ phần đã giữ, vào đúng kỳ UTC lúc giữ chỗ."""
    _adjust(res.key, -res.amount)
