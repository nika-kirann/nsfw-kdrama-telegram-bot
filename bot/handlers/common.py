import functools
import html
from telegram import Update

H = html.escape


def deps(ctx):
    return ctx.bot_data["store"], ctx.bot_data["config"]


def arg_text(update: Update) -> str:
    return (update.message.text or "").partition(" ")[2].strip()


def admin_only(fn):
    @functools.wraps(fn)
    async def wrap(update: Update, ctx):
        if update.effective_user.id not in ctx.bot_data["config"].admin_ids:
            return await update.effective_message.reply_text("🙅 Admins only. Try /browse 😉")
        return await fn(update, ctx)
    return wrap
