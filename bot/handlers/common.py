import re
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


_URL = re.compile(r"https?://\S+")
QUALITIES = ("360p", "480p", "540p", "720p", "1080p", "2160p", "4k")


def parse_links(text):
    """Parse watch links. Each line: 'https://..' (-> Watch) or '720p https://..' / '720p: https://..'.
    Returns (title, {label: url}). A line without a URL becomes the episode title."""
    title, links = None, {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _URL.search(line)
        if not m:
            title = title or line.strip(" |:-")
            continue
        label = line[:m.start()].strip(" :|-") or "Watch"
        links[label[:20]] = m.group(0)
    return title, links


def ep_buttons(e):
    """URL buttons for an episode's watch links (quality links side by side)."""
    from telegram import InlineKeyboardButton as B
    if not e.get("links"):
        return []
    btns = [B(("▶️ " if k == "Watch" else "🎞 ") + k, url=u) for k, u in e["links"].items()]
    return [btns[i:i + 3] for i in range(0, len(btns), 3)]
