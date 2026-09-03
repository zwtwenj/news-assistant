"""图形验证码：captcha 库生成图片，Redis 存码（TTL 5min，一次一用）。"""

import base64
import random
import string
import uuid

from captcha.image import ImageCaptcha

from app.core.redis_client import redis_client

_TTL = 300
_KEY = "captcha:{captcha_id}"
_CHARS = string.digits + "ABCDEFGHJKLMNPQRSTUVWXYZ"  # 去掉易混淆的 I/O


def generate_captcha() -> tuple[str, str]:
    """返回 (captcha_id, data_url)。"""
    captcha_id = uuid.uuid4().hex
    code = "".join(random.choices(_CHARS, k=4))  # noqa: S311
    image = ImageCaptcha(width=160, height=48).generate(code)
    b64 = base64.b64encode(image.getvalue()).decode()
    redis_client.setex(_KEY.format(captcha_id=captcha_id), _TTL, code)
    return captcha_id, f"data:image/png;base64,{b64}"


def check_captcha(captcha_id: str, code: str) -> bool:
    """校验并立即作废（一次一用）。"""
    key = _KEY.format(captcha_id=captcha_id)
    stored = redis_client.get(key)
    if stored is None:
        return False
    redis_client.delete(key)
    return stored == code.upper()
