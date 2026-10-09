from fastapi import APIRouter

from ...realtime import ws
from . import auth, channels, dms, dok, friends, invites, me, meta, moderation, notifications, rtc, search, servers, uploads, users

api_router = APIRouter(prefix="/api/v1")
for module in (auth, me, users, friends, notifications, dms, dok, servers, channels, invites, search, uploads, rtc, moderation, meta):
    api_router.include_router(module.router)
api_router.include_router(ws.router)
