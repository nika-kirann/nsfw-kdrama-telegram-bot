"""Entrypoint: python -m bot"""
import logging
import sys

from telegram import BotCommand, Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application

from . import jobs
from .config import ConfigError, load_config
from .handlers import register
from .health import start_health_server
from .posters import make_poster
from .storage import make_storage
from .store import Store
from .config import ROOT

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # avoid logging token-bearing URLs
log = logging.getLogger("spicy_kdrama")


async def on_error(update, ctx):
    log.error("Unhandled error", exc_info=ctx.error)


async def post_init(app: Application):
    me = await app.bot.get_me()
    log.info("Logged in as @%s, channel=%s", me.username, app.bot_data["config"].channel_id)
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in [
        ("start", "Main menu"), ("browse", "Browse spicy series"), ("latest", "Newest drops"),
        ("search", "Search title / trope"), ("scene", "Random spicy scene"), ("dirty", "Dirty talk line"),
        ("rp", "Character roleplay"), ("request", "Request a story"), ("cancel", "Cancel current action"), ("help", "Help")]])
    await start_storage(app)
    jobs.setup(app)


async def start_storage(app):
    """Restore from the DB channel, then move local poster files into the channel (file_ids survive redeploys)."""
    st, store = app.bot_data["storage"], app.bot_data["store"]
    if st.backend != "telegram":
        log.info("Storage: local (%s)", store.path)
        return
    await st.restore()
    store.on_save = st.schedule_flush
    for s in store.listing():
        p = s.get("poster")
        if p is None or p.startswith("/") or p.startswith("data/"):
            path = make_poster(s, ROOT / "data" / "posters") if (not p or not __import__("os").path.exists(p)) else p
            try:
                s["poster"] = await st.upload_poster(open(path, "rb").read())
            except Exception as e:
                log.warning("Poster upload failed for %s: %s", s["id"], e)
    store.save(flush=False)
    await st.flush()
    log.info("Storage: telegram DB channel ready (backup msg %s)", st.msg_id)


async def post_stop(app):
    await app.bot_data["storage"].close()


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as e:
        log.error("Config error: %s", e); return 1
    app = (Application.builder().token(cfg.token).post_init(post_init).post_stop(post_stop)
           .connect_timeout(30).read_timeout(30).get_updates_read_timeout(40).build())
    store = Store(cfg.data_file)
    app.bot_data.update(config=cfg, store=store, storage=make_storage(cfg, app.bot, store))
    register(app)
    app.add_error_handler(on_error)
    start_health_server()  # only when PORT is set (Koyeb web service)
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except InvalidToken:
        log.error("Telegram rejected the token."); return 1
    except TelegramError as e:
        log.error("Telegram error on startup: %s", e); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
