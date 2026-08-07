from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import TelegramNetworkError

from core.system_proxy import apply_system_proxy, route_fingerprint

from core.backup_service import BackupService
from core.config import settings
from core.database import init_database
from core.feature_flags import feature_flags
from core.notification_service import NotificationService
from core.runtime.migration import migrate_legacy_runtime_layout
from core.payment_service import PaymentMonitor
from core.plugin_loader import register_discovered_games
from core.registry import game_registry
from core.runtime_settings import runtime_settings
from core.startup_checks import log_startup_checks
from core.worker_manager import WorkerManager
from core.shared_service_manager import SharedServiceManager
from telegram.bot import build_bot, build_dispatcher
from games.kintara.molten.channel import MoltenChannelService


LOGGER = logging.getLogger(__name__)
NETWORK_CHECK_SECONDS = 8.0
NETWORK_FAILURE_THRESHOLD = 2
ROUTE_CHANGE_THRESHOLD = 2


async def _close_bot(bot) -> None:
    try:
        await bot.session.close()
    except Exception:
        LOGGER.debug("Could not close Telegram session cleanly", exc_info=True)


async def _connect_fresh_bot():
    """Build a brand-new Telegram session on every retry.

    This is intentionally different from retrying bot.me() forever on one
    aiohttp session. A VPN/proxy change can leave that old session bound to a
    dead connector/route.
    """
    delay = 2.0
    attempt = 0

    while True:
        route = apply_system_proxy()
        bot = build_bot()
        try:
            me = await asyncio.wait_for(bot.get_me(), timeout=10.0)
            LOGGER.info(
                "Telegram connected as @%s | route=%s",
                me.username or me.id,
                route.safe_summary(),
            )
            return bot, route
        except (TelegramNetworkError, asyncio.TimeoutError, OSError) as exc:
            attempt += 1
            await _close_bot(bot)
            LOGGER.warning(
                "Telegram route unavailable (attempt %s, route=%s): %s. "
                "A fresh route/session will be tried in %.0fs",
                attempt,
                route.safe_summary(),
                str(exc).splitlines()[0][:220],
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(20.0, delay * 1.6)


async def _fresh_route_probe() -> bool:
    """Test Telegram through a completely fresh session."""
    apply_system_proxy()
    probe = build_bot()
    try:
        await asyncio.wait_for(probe.get_me(), timeout=7.0)
        return True
    except (TelegramNetworkError, asyncio.TimeoutError, OSError):
        return False
    finally:
        await _close_bot(probe)


async def _network_watchdog(initial_route) -> str:
    initial_fingerprint = route_fingerprint(initial_route)
    failures = 0
    offline_confirmed = False

    candidate_fingerprint = None
    candidate_hits = 0

    while True:
        await asyncio.sleep(NETWORK_CHECK_SECONDS)

        current_route = apply_system_proxy()
        current_fingerprint = route_fingerprint(current_route)

        if current_fingerprint != initial_fingerprint:
            if current_fingerprint == candidate_fingerprint:
                candidate_hits += 1
            else:
                candidate_fingerprint = current_fingerprint
                candidate_hits = 1

            if candidate_hits >= ROUTE_CHANGE_THRESHOLD:
                LOGGER.warning(
                    "Network route changed: %s -> %s. "
                    "Telegram session will be rebuilt.",
                    initial_route.safe_summary(),
                    current_route.safe_summary(),
                )
                return "route-changed"
        else:
            candidate_fingerprint = None
            candidate_hits = 0

        online = await _fresh_route_probe()

        if online:
            if offline_confirmed:
                LOGGER.warning(
                    "Internet/VPN recovered. Telegram session will be rebuilt "
                    "on the fresh route."
                )
                return "network-recovered"
            failures = 0
            continue

        failures += 1
        if failures >= NETWORK_FAILURE_THRESHOLD and not offline_confirmed:
            offline_confirmed = True
            LOGGER.warning(
                "Internet/VPN appears offline. GameBot stays running and waits "
                "for a fresh route instead of pinning the old Telegram session."
            )


async def _stop_polling(dispatcher) -> None:
    try:
        await dispatcher.stop_polling()
    except RuntimeError:
        pass
    except Exception:
        LOGGER.debug("Could not stop dispatcher cleanly", exc_info=True)


async def _run_telegram_session(
    worker_manager: WorkerManager,
    shared_service_manager: SharedServiceManager,
) -> str:
    bot, route = await _connect_fresh_bot()

    payment_monitor = PaymentMonitor(bot, worker_manager)
    notification_service = NotificationService(bot)
    molten_channel_service = MoltenChannelService(bot)

    await payment_monitor.start()
    await notification_service.start()
    await molten_channel_service.start()

    dispatcher = build_dispatcher(
        worker_manager,
        payment_monitor,
        _run_telegram_session.backup_service,
        shared_service_manager,
        molten_channel_service,
    )

    polling_task = asyncio.create_task(
        dispatcher.start_polling(bot, handle_signals=False),
        name="telegram-polling",
    )
    watchdog_task = asyncio.create_task(
        _network_watchdog(route),
        name="telegram-network-watchdog",
    )

    reason = "polling-ended"
    try:
        done, _ = await asyncio.wait(
            {polling_task, watchdog_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if watchdog_task in done:
            reason = watchdog_task.result()
            if not polling_task.done():
                await _stop_polling(dispatcher)
                try:
                    await asyncio.wait_for(polling_task, timeout=12.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    polling_task.cancel()
                    await asyncio.gather(polling_task, return_exceptions=True)
        else:
            watchdog_task.cancel()
            await asyncio.gather(watchdog_task, return_exceptions=True)

            if polling_task.cancelled():
                raise asyncio.CancelledError

            error = polling_task.exception()
            if error is not None:
                if isinstance(error, TelegramNetworkError):
                    reason = "polling-network-error"
                    LOGGER.warning(
                        "Telegram polling session ended with a network error; "
                        "a fresh session will be created: %s",
                        str(error).splitlines()[0][:220],
                    )
                else:
                    raise error
    finally:
        for task in (watchdog_task, polling_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(watchdog_task, polling_task, return_exceptions=True)

        await asyncio.gather(
            molten_channel_service.stop(),
            notification_service.stop(),
            payment_monitor.stop(),
            return_exceptions=True,
        )
        await _close_bot(bot)

    return reason


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    migrate_legacy_runtime_layout()
    await init_database()
    await runtime_settings.load()
    log_startup_checks()

    await feature_flags.start()
    plugins = register_discovered_games(game_registry)
    if not plugins:
        raise RuntimeError("No game plugins were discovered")

    worker_manager = WorkerManager(game_registry)
    await worker_manager.start_supervisor()
    await worker_manager.restore_workers()

    shared_service_manager = SharedServiceManager()
    await shared_service_manager.start_supervisor()
    await shared_service_manager.restore_services()

    backup_service = BackupService()
    _run_telegram_session.backup_service = backup_service
    await backup_service.start()

    try:
        while True:
            reason = await _run_telegram_session(
                worker_manager,
                shared_service_manager,
            )
            LOGGER.info(
                "Rebuilding Telegram networking session (%s)...",
                reason,
            )
            await asyncio.sleep(1.5)
    finally:
        await asyncio.gather(
            backup_service.stop(),
            shared_service_manager.shutdown(),
            worker_manager.shutdown(),
            feature_flags.stop(),
            return_exceptions=True,
        )


# Runtime attribute is assigned in main before the first Telegram session.
_run_telegram_session.backup_service = None


if __name__ == "__main__":
    asyncio.run(main())
