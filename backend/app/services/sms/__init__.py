"""SMS Provider 统一入口：按 SMS_PROVIDER 配置选择实现（plan-auth §2.1）。"""

from typing import Protocol

from app.core.config import get_settings


class SMSProvider(Protocol):
    def send_code(self, phone: str) -> bool:
        """发送验证码（验证码由实现方生成：aliyun=云端 ##code##，mock=本地随机）。"""
        ...

    def verify_code(self, phone: str, code: str) -> bool:
        """核验验证码。"""
        ...


def get_sms_provider() -> SMSProvider:
    settings = get_settings()
    if settings.sms_provider == "aliyun":
        from app.services.sms.aliyun import AliyunSmsProvider

        return AliyunSmsProvider()
    from app.services.sms.mock import MockSmsProvider

    return MockSmsProvider()


sms_provider = get_sms_provider()
