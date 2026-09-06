# 新闻助手

多用户新闻采集 + 播客生成产品，AI 聊天助手为二期增强。项目计划见 [plan.md](./plan.md)。

## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.0（同步）+ PostgreSQL + Alembic
- **异步任务**：Celery + Redis（按资源画像分队队：crawl / llm / media / default）
- **前端**：Next.js（TypeScript + Tailwind）
- **LLM**：统一 provider 网关（DeepSeek / 智谱 / 百炼 / MiniMax，OpenAI 兼容协议）
- **向量库**：火山引擎 Milvus Serverless（M1 后期接入）

## 目录结构

```
├── plan.md               # 项目计划（生产级 v2）
├── docker-compose.yml    # 开发环境基础设施（PG + Redis）
├── deploy/               # prod 部署文件（M1 后期补充）
├── backend/
│   ├── app/
│   │   ├── core/         # 配置、日志
│   │   ├── api/v1/       # 路由（/api/v1）
│   │   ├── db/           # engine / session / Base
│   │   ├── models/       # ORM 模型
│   │   ├── schemas/      # Pydantic 模型
│   │   ├── services/llm/ # LLM provider 网关
│   │   └── tasks/        # Celery 应用 + 四队列任务
│   ├── alembic/          # 数据库迁移
│   ├── tests/
│   └── .env.example      # 配置模板（真实 .env 不入库）
└── frontend/             # Next.js（src/app 结构）
```

## 本地开发

### 1. 基础设施（二选一）

```bash
# 方式 A：本地 Docker（默认）
docker compose up -d        # PG(5432) + Redis(6379)

# 方式 B：直连服务器容器（本地无需 Docker）
cd backend && uv run python scripts/switch_infra.py server
# 切换会改写 .env 的 DATABASE_URL/REDIS_URL（server 连接串缓存于 infra-server.env）
# 之后再切回本地：uv run python scripts/switch_infra.py local
```

### 2. 后端

```bash
cd backend
cp .env.example .env        # 首次：填入密钥（本机已有现成 .env 则跳过）
uv sync                     # 安装依赖（Python 3.13，见 .python-version）
uv run alembic upgrade head # 数据库迁移
uv run uvicorn app.main:app --reload --port 8000
```

验证：http://localhost:8000/healthz 与 http://localhost:8000/docs

### 3. Celery worker（按队列启动，可开多个终端）

```bash
cd backend
uv run celery -A app.tasks worker -Q crawl -c 8 -n crawl@%h --pool=solo   # Windows 开发需 --pool=solo
uv run celery -A app.tasks worker -Q llm -c 4 -n llm@%h --pool=solo
uv run celery -A app.tasks worker -Q media,default -c 2 -n media@%h --pool=solo
```

> Linux/生产环境去掉 `--pool=solo`。

### 4. 前端

```bash
cd frontend
npm install                 # 首次
npm run dev                 # http://localhost:3000
```

首页是脚手架状态面板，展示后端与依赖服务的连通性（通过 Next.js rewrites 代理 `/api/*` 到 8000 端口）。

### 5. 测试与 Lint

```bash
cd backend
uv run pytest
uv run ruff check .
```

## 环境变量

见 `backend/.env.example`。**真实 `.env` 已被 .gitignore 排除，永不入库**；上线前须轮换所有密钥（见 plan.md §9）。
