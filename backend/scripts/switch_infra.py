"""本地开发基础设施一键切换（server / local）。

- server：PG/Redis 用服务器（198.44.177.247）上的容器，本地无需 Docker
- local ：本地 docker compose 起 PG/Redis（news/news，无密码 Redis）

用法：
  uv run python scripts/switch_infra.py          # 查看当前模式
  uv run python scripts/switch_infra.py server   # 切到服务器容器
  uv run python scripts/switch_infra.py local    # 切到本地 Docker

首次从 local 切回 server 需要服务器凭据：从 infra-server.env 缓存读取
（由本脚本自动生成，*.env 已被 gitignore）。缓存缺失时报错并给出指引。
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
CACHE_FILE = ENV_FILE.parent / "infra-server.env"
SERVER_HOST = "198.44.177.247"

LOCAL_DB = "postgresql+psycopg://news:news@localhost:5432/news"
LOCAL_REDIS = "redis://localhost:6379/0"


def read_env() -> str:
    if not ENV_FILE.exists():
        logger.error("缺少 {}（参照 .env.example 配置）", ENV_FILE.name)
        sys.exit(1)
    return ENV_FILE.read_text(encoding="utf-8")


def current_mode(content: str) -> str:
    m = re.search(r"^DATABASE_URL=.*@([^:/]+)", content, re.M)
    if not m:
        logger.error(".env 中无 DATABASE_URL，无法识别模式")
        sys.exit(1)
    return "server" if m.group(1) == SERVER_HOST else "local"


def rewrite(content: str, db_url: str, redis_url: str) -> str:
    # 连标记行整行移除（含换行），避免切换循环累积空行
    content = re.sub(r"^# INFRA=.*\n?", "", content, flags=re.M)
    content = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={db_url}", content, flags=re.M)
    content = re.sub(r"^REDIS_URL=.*$", f"REDIS_URL={redis_url}", content, flags=re.M)
    lines = content.splitlines(keepends=True)
    marker = f"# INFRA={'server' if SERVER_HOST in db_url else 'local'}"
    # 标记插在首个非注释行前，保证肉眼可见
    insert_at = next(
        (i for i, ln in enumerate(lines) if ln.strip() and not ln.startswith("#")), 0
    )
    lines.insert(insert_at, marker + "\n")
    return "".join(lines)


def main() -> None:
    content = read_env()
    cur = current_mode(content)
    target = sys.argv[1] if len(sys.argv) > 1 else cur
    if target not in ("server", "local"):
        print(__doc__)
        sys.exit(1)
    if target == cur:
        logger.info("当前已是 {} 模式，无需切换", cur)
        return

    if target == "local":
        # 缓存服务器连接串，便于日后切回
        db = re.search(r"^DATABASE_URL=(.*)$", content, re.M).group(1)
        redis = re.search(r"^REDIS_URL=(.*)$", content, re.M).group(1)
        CACHE_FILE.write_text(f"DATABASE_URL={db}\nREDIS_URL={redis}\n", encoding="utf-8")
        ENV_FILE.write_text(rewrite(content, LOCAL_DB, LOCAL_REDIS), encoding="utf-8")
        logger.info("已切到 local：docker compose up -d 后重启本地服务")
    else:
        if not CACHE_FILE.exists():
            logger.error(
                "缺少 {}（服务器连接串缓存）。请手工在 .env 填入服务器连接串后重跑，"
                "本脚本会自动补缓存", CACHE_FILE.name,
            )
            sys.exit(1)
        cache = CACHE_FILE.read_text(encoding="utf-8")
        db = re.search(r"^DATABASE_URL=(.*)$", cache, re.M).group(1)
        redis = re.search(r"^REDIS_URL=(.*)$", cache, re.M).group(1)
        ENV_FILE.write_text(rewrite(content, db, redis), encoding="utf-8")
        logger.info("已切到 server（{}），无需本地 Docker", SERVER_HOST)


if __name__ == "__main__":
    main()
