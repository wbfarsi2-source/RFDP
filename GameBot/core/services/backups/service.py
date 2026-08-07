from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

from sqlalchemy.engine import make_url

from core.config import settings
from core.runtime_settings import runtime_settings

logger = logging.getLogger(__name__)


class BackupService:
    def __init__(self) -> None:
        self.backup_dir = Path("data/backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def create_backup(self) -> Path:
        return await asyncio.to_thread(self._create_backup_sync)

    def _create_backup_sync(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        work = self.backup_dir / f"work-{stamp}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            url = make_url(settings.database_url)
            if url.get_backend_name() == "sqlite":
                source = Path(url.database or "data/gamebot.db")
                destination = work / "gamebot.db"
                if source.exists():
                    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
                        src.backup(dst)
            else:
                (work / "DATABASE_BACKUP_REQUIRED.txt").write_text(
                    "This installation uses a non-SQLite database. Use the database server backup tool.",
                    encoding="utf-8",
                )

            for path in (
                Path("games"),
                Path(settings.instances_dir),
                Path(settings.shared_services_dir),
                Path("README_FA.md"),
                Path(".env.example"),
            ):
                if path.is_dir():
                    shutil.copytree(path, work / path.name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                elif path.exists():
                    shutil.copy2(path, work / path.name)
            if settings.backup_include_env and Path(".env").exists():
                shutil.copy2(".env", work / ".env")

            archive = self.backup_dir / f"gamebot-backup-{stamp}.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in work.rglob("*"):
                    if file.is_file():
                        zf.write(file, file.relative_to(work))
            self._cleanup_old()
            return archive
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _cleanup_old(self) -> None:
        rows = sorted(self.backup_dir.glob("gamebot-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in rows[runtime_settings.backup_keep_last():]:
            path.unlink(missing_ok=True)

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await asyncio.sleep(runtime_settings.backup_interval_seconds())
                archive = await self.create_backup()
                logger.info("Automatic backup created: %s", archive)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Automatic backup failed")
