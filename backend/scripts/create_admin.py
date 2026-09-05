"""后管管理员建号脚本（无注册端点，唯一建号入口；幂等：存在则改密）。

用法：
  uv run python scripts/create_admin.py <username> <password> [display_name]
  容器内：docker compose exec -T web python scripts/create_admin.py <username> <password>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from app.db.session import SessionLocal
from app.models.admin_user import AdminUser
from app.services.auth.password import hash_password


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]
    display_name = sys.argv[3] if len(sys.argv) == 4 else None
    if len(password) < 8:
        logger.error("密码至少 8 位")
        sys.exit(1)

    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.username == username).first()
        if admin:
            admin.password_hash = hash_password(password)
            admin.status = "active"
            action = "改密并启用"
        else:
            admin = AdminUser(
                username=username, password_hash=hash_password(password), display_name=display_name
            )
            db.add(admin)
            action = "创建"
        db.commit()
        logger.info("管理员 {} {}：{}", username, action, display_name or "-")
    finally:
        db.close()


if __name__ == "__main__":
    main()
