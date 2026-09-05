"""密码哈希（pwdlib bcrypt，后管账号用；C 端短信登录不涉及密码）。"""

from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

_hasher = PasswordHash((BcryptHasher(),))


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _hasher.verify(raw, hashed)
