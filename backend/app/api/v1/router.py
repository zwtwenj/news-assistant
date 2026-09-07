from fastapi import APIRouter

from app.api.v1 import auth, chat, health, hosts, news, podcasts, rss, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(news.router)
api_router.include_router(podcasts.router)
api_router.include_router(hosts.router)
api_router.include_router(rss.router)
api_router.include_router(chat.router)
