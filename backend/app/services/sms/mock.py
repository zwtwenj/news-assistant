"""开发用 Mock：验证码本地生成存 Redis（TTL 5min），核验对 Redis。"""

from loguru import logger

from app.core.redis_client import redis_client

_TTL_SECONDS = 300  # 与 aliyun ValidTime 对齐
_KEY = "mock:sms:code:{phone}"


class MockSmsProvider:
    def send_code(self, phone: str) -> bool:
        import random

        code = f"{random.randint(0, 999999):06d}"
        redis_client.setex(_KEY.format(phone=phone), _TTL_SECONDS, code)
        logger.info("[MOCK SMS] phone={} code={}（5分钟内有效）", phone, code)
        return True

    def verify_code(self, phone: str, code: str) -> bool:
        key = _KEY.format(phone=phone)
        stored = redis_client.get(key)
        ok = stored is not None and stored == code
        if ok:
            redis_client.delete(key)  # 一次一码：核验通过即作废
        return ok
