"""API v1 routers."""

from fastapi import APIRouter

from cara.api.v1 import admin, auth, chat, conversations, family, files, news, notes, radio, shopping, tasks

router = APIRouter(prefix="/api/v1")
router.include_router(admin.router)
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(conversations.router)
router.include_router(family.router)
router.include_router(files.router)
router.include_router(news.router)
router.include_router(notes.router)
router.include_router(radio.router)
router.include_router(shopping.router)
router.include_router(tasks.router)
