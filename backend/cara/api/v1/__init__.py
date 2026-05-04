"""API v1 routers."""

from fastapi import APIRouter

from cara.api.v1 import (
    admin,
    admin_learning,
    asr,
    auth,
    budgets,
    cda,
    chat,
    conversations,
    device_aliases,
    diagnostics,
    events,
    family,
    files,
    memory,
    news,
    notes,
    radio,
    shopping,
    smarthome,
    tasks,
    tools,
    voice,
    weather,
    widgets,
)

router = APIRouter(prefix="/api/v1")
router.include_router(admin.router)
router.include_router(admin_learning.router)
router.include_router(asr.router)
router.include_router(auth.router)
router.include_router(budgets.router)
router.include_router(cda.router)
router.include_router(chat.router)
router.include_router(conversations.router)
router.include_router(device_aliases.router)
router.include_router(diagnostics.router)
router.include_router(events.router)
router.include_router(family.router)
router.include_router(files.router)
router.include_router(memory.router)
router.include_router(news.router)
router.include_router(notes.router)
router.include_router(radio.router)
router.include_router(shopping.router)
router.include_router(smarthome.router)
router.include_router(tasks.router)
router.include_router(tools.router)
router.include_router(voice.router)
router.include_router(weather.router)
router.include_router(widgets.router)
