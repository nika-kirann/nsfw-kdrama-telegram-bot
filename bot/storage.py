"""Channel-as-database (ported from heaven-bot storage.py, JSON instead of SQLite).

STORAGE_BACKEND=telegram: data/series.json is mirrored to a private DB channel (DB_CHANNEL_ID):
  * startup: the pinned `spicy-backup.json` document is downloaded and loaded before polling
  * every Store.save() schedules a debounced flush that replaces the pinned document
    (edit_message_media; falls back to send + pin + delete old)
  * clean shutdown: final flush
  * posters stored as local files are uploaded to the DB channel and replaced by Telegram file_ids,
    so they survive Koyeb's ephemeral disk.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from telegram import InputFile, InputMediaDocument
from telegram.error import BadRequest, TelegramError

log = logging.getLogger(__name__)
BACKUP_NAME = "spicy-backup.json"


class LocalStorage:
    backend = "local"

    async def restore(self, store):
        return False

    def schedule_flush(self):
        pass

    async def flush(self):
        pass

    async def close(self):
        pass


class TelegramStorage:
    backend = "telegram"

    def __init__(self, bot, chat_id, store, delay=3.0):
        self.bot, self.chat_id, self.store, self.delay = bot, chat_id, store, delay
        self.msg_id = None
        self._task = None
        self._lock = asyncio.Lock()
        self.enabled = False

    async def restore(self) -> bool:
        self.enabled = True
        chat = await self.bot.get_chat(self.chat_id)
        pm = chat.pinned_message
        doc = getattr(pm, "document", None) if pm else None
        if not doc or doc.file_name != BACKUP_NAME:
            log.info("DB channel: no pinned backup, starting from local/seed data")
            return False
        self.msg_id = pm.message_id
        raw = await (await self.bot.get_file(doc.file_id)).download_as_bytearray()
        try:
            data = json.loads(bytes(raw))
            assert "series" in data
        except Exception:
            log.error("DB channel: pinned backup is not valid JSON; ignoring")
            return False
        self.store.d = data
        self.store._migrate()
        self.store.save(flush=False)
        log.info("DB channel: restored %s series from message %s", len(data["series"]), pm.message_id)
        return True

    def schedule_flush(self):
        if not self.enabled:
            return
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = asyncio.get_event_loop().create_task(self._delayed())

    async def _delayed(self):
        try:
            await asyncio.sleep(self.delay)
            await self.flush()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("DB channel: flush failed (retry on next write)")

    async def flush(self):
        if not self.enabled:
            return
        async with self._lock:
            data = json.dumps(self.store.d, ensure_ascii=False).encode()
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            cap = f"🗄 spicy bot DB · {stamp} · {len(data)} bytes. Keep pinned, don't delete."
            if self.msg_id:
                try:
                    await self.bot.edit_message_media(chat_id=self.chat_id, message_id=self.msg_id,
                                                      media=InputMediaDocument(data, filename=BACKUP_NAME, caption=cap))
                    return
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        return
                    log.warning("DB channel: edit failed (%s); sending new backup", e)
            msg = await self.bot.send_document(self.chat_id, InputFile(data, filename=BACKUP_NAME),
                                               caption=cap, disable_notification=True)
            old, self.msg_id = self.msg_id, msg.message_id
            await self.bot.pin_chat_message(self.chat_id, msg.message_id, disable_notification=True)
            if old:
                try:
                    await self.bot.delete_message(self.chat_id, old)
                except TelegramError:
                    pass

    async def upload_poster(self, photo) -> str:
        msg = await self.bot.send_photo(self.chat_id, photo, caption="🖼 poster", disable_notification=True)
        return msg.photo[-1].file_id

    async def close(self):
        if self._task and not self._task.done():
            self._task.cancel()
        if self.enabled:
            try:
                await self.flush(); log.info("DB channel: final flush done")
            except Exception:
                log.exception("DB channel: final flush failed")
        self.enabled = False


def make_storage(cfg, bot, store):
    if cfg.storage_backend == "telegram" and cfg.db_channel_id:
        return TelegramStorage(bot, cfg.db_channel_id, store, cfg.flush_delay)
    return LocalStorage()
