"""PNVS 短信认证连通性探测脚本。

用途：分层定位问题——鉴权(AK/Secret) → 服务开通(PNVS) → 签名/模板配置。
用法：
  uv run python scripts/probe_sms.py 手机号              # 发送验证码
  uv run python scripts/probe_sms.py verify 手机号 验证码  # 核验验证码
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alibabacloud_dypnsapi20170525.client import Client
from alibabacloud_dypnsapi20170525.models import SendSmsVerifyCodeRequest
from alibabacloud_tea_openapi.models import Config

from app.core.config import get_settings

DIAGNOSIS = {
    "InvalidAccessKeyId.NotFound": "AK 不存在（检查是否复制完整/已被禁用）",
    "InvalidAccessKeyId.Inactive": "AK 已禁用",
    "SignatureDoesNotMatch": "Secret 与 AK 不匹配",
    "Forbidden.SubUser": "RAM 子账号未授权号码认证服务权限（需 AliyunDypnsApiFullAccess）",
    "Forbidden.RAM": "RAM 授权问题",
    "Forbidden.NoPermission": (
        "鉴权通过 ✓ 但 RAM 子账号缺少号码认证服务授权 → 授 AliyunDypnsApiFullAccess"
    ),
    "403": "鉴权通过 ✓ 但权限不足/服务未开通 → 检查 RAM 授权与 PNVS 开通状态",
    "FUNCTION_NOT_OPENED": "鉴权已通过 ✓ 但号码认证服务(PNVS)未开通 → 控制台开通「号码认证服务」",
    "isv.BUSINESS_LIMIT_CONTROL": "鉴权已通过 ✓ 该号码触发天级流控",
    "MOBILE_NUMBER_ILLEGAL": "鉴权已通过 ✓ 手机号格式非法",
    "INVALID_PARAMETERS": "鉴权已通过 ✓ 参数错误（签名/模板占位符导致，属预期）",
    "isv.SMS_SIGNATURE_ILLEGAL": "鉴权已通过 ✓ 签名不存在 → 需填 PNVS 赠送签名",
    "isv.SMS_TEMPLATE_ILLEGAL": "鉴权已通过 ✓ 模板不存在 → 需填 PNVS 配套模板 CODE",
}


def verify(phone: str, code: str) -> None:
    """调 CheckSmsVerifyCode 核验（注意：Code=OK 不代表核验成功，看 VerifyResult）。"""
    s = get_settings()
    client = Client(
        Config(
            access_key_id=s.sms_aliyun_ak,
            access_key_secret=s.sms_aliyun_secret,
            endpoint="dypnsapi.aliyuncs.com",
        )
    )
    from alibabacloud_dypnsapi20170525.models import CheckSmsVerifyCodeRequest

    req = CheckSmsVerifyCodeRequest(phone_number=phone, verify_code=code)
    try:
        body = client.check_sms_verify_code(req).body
        result = getattr(body, "model", None)
        verify_result = getattr(result, "verify_result", "?") if result else "?"
        print(f"调用返回: Code={body.code} Message={body.message}")
        passed = verify_result == "PASS"
        print(f"核验结果: VerifyResult={verify_result} {'✓ 通过' if passed else '✗ 未通过'}")
    except Exception as e:  # noqa: BLE001
        print(f"✗ 异常: {getattr(e, 'message', e)}")


def main() -> None:
    s = get_settings()
    if len(sys.argv) >= 4 and sys.argv[1] == "verify":
        verify(sys.argv[2], sys.argv[3])
        return
    phone = sys.argv[1] if len(sys.argv) > 1 else "13800138000"

    print(f"AK: {s.sms_aliyun_ak[:8]}...")
    if not s.sms_aliyun_ak or not s.sms_aliyun_secret:
        print("✗ 缺少 AK/Secret")
        return

    client = Client(
        Config(
            access_key_id=s.sms_aliyun_ak,
            access_key_secret=s.sms_aliyun_secret,
            endpoint="dypnsapi.aliyuncs.com",
        )
    )
    req = SendSmsVerifyCodeRequest(
        phone_number=phone,
        sign_name=s.sms_sign_name or "占位签名",
        template_code=s.sms_template_code or "00000000",
        template_param='{"code":"##code##","min":"5"}',
        code_length=6,
        valid_time=300,
        interval=60,
        duplicate_policy=1,
        return_verify_code=False,
    )
    try:
        resp = client.send_sms_verify_code(req)
        body = resp.body
        print(f"调用返回: Code={body.code} Message={body.message}")
        if body.code == "OK":
            print("✓✓ 发送成功！签名/模板配置有效，可真实收到短信")
    except Exception as e:  # noqa: BLE001  Tea 错误也走这里，code/message 用 getattr 取
        code = str(getattr(e, "code", "") or "")
        print(f"✗ 错误码: {code}")
        print(f"  消息: {getattr(e, 'message', str(e))}")
        for key, diag in DIAGNOSIS.items():
            if key.lower() in str(e).lower():
                print(f"→ 诊断: {diag}")
                break
        else:
            print("→ 未匹配到已知错误码，把上面的信息发我")


if __name__ == "__main__":
    main()
