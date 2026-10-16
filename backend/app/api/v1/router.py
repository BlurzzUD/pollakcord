from fastapi import APIRouter

from ...realtime import ws
from ...realtime import bots as bot_gateway
from . import auth, bots, channels, class_spaces, dms, dok, forms, friends, invites, me, meta, moderation, notifications, rtc, search, servers, uploads, users

api_router = APIRouter(prefix="/api/v1")
for module in (bots, auth, me, users, friends, notifications, dms, dok, forms, class_spaces, servers, channels, invites, search, uploads, rtc, moderation, meta):
    api_router.include_router(module.router)
api_router.include_router(ws.router)
api_router.include_router(bot_gateway.router)
