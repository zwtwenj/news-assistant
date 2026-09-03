"""阿里云 PNVS 短信认证（已实测闭环：发送 Code=OK，核验 VerifyResult=PASS）。

两个坑（来自实测/文档）：
1. CheckSmsVerifyCode 返回 Code=OK ≠ 核验成功，必须看 Model.VerifyResult == "PASS"；
2. 模板 100001 有两个变量：TemplateParam 需 {"code":"##code##","min":"5"}，
   min 与 ValidTime(300s) 对应。
"""

from typing import Any

from alibabacloud_dypnsapi20170525.client import Client
from alibabacloud_dypnsapi20170525.models import (
    CheckSmsVerifyCodeRequest,
    SendSmsVerifyCodeRequest,
)
from alibabacloud_tea_openapi.models import Config
from loguru import logger

from app.core.config import get_settings


class AliyunSmsProvider:
    def __init__(self) -> None:
        s = get_settings()
        self._client = Client(
            Config(
                access_key_id=s.sms_aliyun_ak,
                access_key_secret=s.sms_aliyun_secret,
                endpoint="dypnsapi.aliyuncs.com",
                connect_timeout=5000,
                read_timeout=10000,
            )
        )
        self._sign_name = s.sms_sign_name
        self._template_code = s.sms_template_code

    def send_code(self, phone: str) -> bool:
        req = SendSmsVerifyCodeRequest(
            phone_number=phone,
            sign_name=self._sign_name,
            template_code=self._template_code,
            template_param='{"code":"##code##","min":"5"}',
            code_length=6,
            valid_time=300,
            interval=60,  # 云端同号 60s 频控（与本地防刷对齐）
            duplicate_policy=1,  # 新码覆盖旧码（一次一码）
            return_verify_code=False,
        )
        try:
            body = self._client.send_sms_verify_code(req).body
        except Exception:  # noqa: BLE001  网络层失败
            logger.opt(exception=True).error("sms send fail phone={}", phone)
            return False
        if body.code == "OK":
            logger.info("sms sent ok phone={}", phone)
            return True
        # 频控/流控等业务错误码透传日志（FREQUENCY_FAIL / BUSINESS_LIMIT_CONTROL 等）
        logger.warning("sms send rejected phone={} code={} msg={}", phone, body.code, body.message)
        return False

    def verify_code(self, phone: str, code: str) -> bool:
        req = CheckSmsVerifyCodeRequest(phone_number=phone, verify_code=code)
        try:
            body: Any = self._client.check_sms_verify_code(req).body
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).error("sms verify fail phone={}", phone)
            return False
        model = getattr(body, "model", None)
        verify_result = getattr(model, "verify_result", None) if model else None
        passed = verify_result == "PASS"
        logger.info("sms verify phone={} result={}", phone, verify_result)
        return passed
