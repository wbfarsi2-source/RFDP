from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from core.backup_service import BackupService
from core.config import settings
from core.payment_service import PaymentMonitor
from core.shared_service_manager import SharedServiceManager
from core.system_proxy import proxy_url_for
from core.worker_manager import WorkerManager
from games.kintara.molten.channel import MoltenChannelService
from games.kintara.telegram import router as kintara_router
from telegram.middlewares import MaintenanceMiddleware
from telegram.routers import accounts, admin, fallback, payments, start


def build_bot() -> Bot:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Put it in .env")
    proxy_url = proxy_url_for("https://api.telegram.org")
    session = AiohttpSession(proxy=proxy_url) if proxy_url else AiohttpSession()
    return Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(
    worker_manager: WorkerManager,
    payment_monitor: PaymentMonitor,
    backup_service: BackupService,
    shared_service_manager: SharedServiceManager,
    molten_channel_service: MoltenChannelService,
) -> Dispatcher:
    dispatcher = Dispatcher()
    maintenance = MaintenanceMiddleware()
    dispatcher.message.outer_middleware(maintenance)
    dispatcher.callback_query.outer_middleware(maintenance)
    dispatcher["worker_manager"] = worker_manager
    dispatcher["payment_monitor"] = payment_monitor
    dispatcher["backup_service"] = backup_service
    dispatcher["shared_service_manager"] = shared_service_manager
    dispatcher["molten_channel_service"] = molten_channel_service
    dispatcher.include_router(start.router)
    dispatcher.include_router(kintara_router.router)
    dispatcher.include_router(accounts.router)
    dispatcher.include_router(payments.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(fallback.router)
    return dispatcher
