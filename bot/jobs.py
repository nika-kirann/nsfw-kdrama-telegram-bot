"""Scheduled posts + daily digest (ported from heaven-bot's jobs.py)."""
import datetime as dt
import html
import logging
import time

from .channel import post_to_channel

log = logging.getLogger(__name__)


def queue_schedule(app, sc):
    async def run(ctx):
        store, cfg = ctx.bot_data["store"], ctx.bot_data["config"]
        if cfg.channel_id:
            await post_to_channel(ctx.bot, cfg.channel_id, sc["text"])
        sc["done"] = True; store.save()
    app.job_queue.run_once(run, when=max(1, sc["at"] - time.time()), name=f"schedule:{sc['id']}")


async def daily_digest(ctx) -> bool:
    store, cfg = ctx.bot_data["store"], ctx.bot_data["config"]
    new = store.new_eps_since(time.time() - 86400)
    if not new or not cfg.channel_id:
        return False
    lines = [f"• <b>{html.escape(s['title'])}</b> EP {e['n']}" for s, e in new]
    await post_to_channel(ctx.bot, cfg.channel_id, "🌙 <b>Tonight's spicy drops</b> 🔥\n\n" + "\n".join(lines))
    return True


def setup(app):
    store, cfg = app.bot_data["store"], app.bot_data["config"]
    for sc in store.d["schedules"]:
        if not sc["done"]:
            queue_schedule(app, sc)  # missed ones fire right away
    h, m = map(int, cfg.digest_time.split(":"))
    app.job_queue.run_daily(daily_digest, dt.time(h, m, tzinfo=cfg.tz), name="digest")
