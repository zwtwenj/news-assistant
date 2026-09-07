"""阿里云 OSS 上传（播客音频终存）。

对齐 demo（icarus-magic-server）用法：公有读 bucket，audio_url 存
`https://{bucket}.{endpoint_host}/{key}` 直链。AK 未配置时 enabled() 为 False，
调用方回退本地 /media 路径，不影响生成链路。
"""

from pathlib import Path

import oss2
from loguru import logger

from app.core.config import get_settings

TIMEOUT = 120  # 播客 mp3 ~2MB，充足


def enabled() -> bool:
    s = get_settings()
    return bool(s.oss_access_key_id and s.oss_secret)


def _bucket() -> oss2.Bucket:
    s = get_settings()
    auth = oss2.Auth(s.oss_access_key_id, s.oss_secret)
    return oss2.Bucket(auth, s.oss_endpoint, s.oss_bucket, connect_timeout=TIMEOUT)


def public_url(object_key: str) -> str:
    """虚拟主机式直链：https://{bucket}.{endpoint_host}/{key}（要求 bucket 公共读）。"""
    s = get_settings()
    host = s.oss_endpoint.removeprefix("https://").removeprefix("http://")
    return f"https://{s.oss_bucket}.{host}/{object_key}"


def upload_file(local: Path | str, object_key: str) -> str | None:
    """上传本地文件，成功返回公有读直链，失败返回 None（调用方降级本地）。"""
    try:
        path = Path(local)
        _bucket().put_object_from_file(object_key, str(path))
        url = public_url(object_key)
        logger.info("oss upload ok {} -> {} ({}B)", path.name, object_key, path.stat().st_size)
        return url
    except Exception as exc:
        logger.error("oss upload fail {}: {}", object_key, exc)
        return None


def upload_bytes(data: bytes, object_key: str, content_type: str | None = None) -> str | None:
    """上传内存字节（用户上传的封面图等），成功返回公有读直链，失败返回 None。"""
    try:
        headers = {"Content-Type": content_type} if content_type else None
        _bucket().put_object(object_key, data, headers=headers)
        url = public_url(object_key)
        tail = object_key.split("/")[-1]
        logger.info("oss upload ok {} -> {} ({}B)", tail, object_key, len(data))
        return url
    except Exception as exc:
        logger.error("oss upload fail {}: {}", object_key, exc)
        return None


def object_exists(object_key: str) -> bool:
    return _bucket().object_exists(object_key)
