"""Admin commands (ported from heaven-bot): /add /addep /complete /edit /delete /list /stats /post /repost
/schedule /schedules /digest /admin."""
import datetime as dt
import random

from telegram.constants import ParseMode
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import CommandHandler, MessageHandler, filters

from .. import jobs
from ..config import ROOT
from ..posters import make_poster
from ..channel import announce_episode, post_card, post_to_channel
from ..content import random_from
from .common import H, admin_only, arg_text, deps

HTML = ParseMode.HTML


async def _need_channel(update, cfg):
    if not cfg.channel_id:
        await update.message.reply_text("CHANNEL_ID not set in .env.")
        return False
    return True


@admin_only
async def add(update, ctx):
    """/add Title | tag1, tag2 | heat 1-5 | synopsis"""
    store, cfg = deps(ctx)
    p = [x.strip() for x in arg_text(update).split("|")]
    if len(p) < 4 or not p[2].isdigit():
        return await update.message.reply_text("Usage: /add Title | Trope1, Trope2 | heat(1-5) | synopsis")
    s = store.add_series(p[0], p[3], [t.strip() for t in p[1].split(",") if t.strip()], heat=max(1, min(5, int(p[2]))))
    pth = str(make_poster(s, POSTER_DIR))
    st = ctx.bot_data.get("storage")
    if st and st.backend == "telegram":
        pth = await st.upload_poster(open(pth, "rb").read())
    store.update(s["id"], poster=pth)
    msg = f"✅ Added #{s['id']} {H(s['title'])}. Add episodes with /addep {s['id']} &lt;text&gt;"
    if cfg.channel_id:
        try:
            await post_card(ctx.bot, cfg, store, s); msg += "\n📤 Card posted to channel."
        except Exception as e:
            msg += f"\n⚠️ Channel post failed: {H(str(e))}"
    await update.message.reply_text(msg, parse_mode=HTML)


@admin_only
async def addep(update, ctx):
    """/addep <id|title> then episode text on the next lines."""
    store, cfg = deps(ctx)
    first, _, body = arg_text(update).partition("\n")
    s = store.find(first)
    if not s or not body.strip():
        return await update.message.reply_text("Usage:\n/addep <id or title>\n<episode text on following lines>")
    n = store.add_episode(s["id"], H(body.strip()))
    msg = f"🆕 EP {n} added to {H(s['title'])}."
    if cfg.channel_id:
        try:
            await post_card(ctx.bot, cfg, store, s); await announce_episode(ctx.bot, cfg, s, n)
            msg += " Card updated + drop announced."
        except Exception as e:
            msg += f" ⚠️ Channel: {H(str(e))}"
    await update.message.reply_text(msg, parse_mode=HTML)


@admin_only
async def complete(update, ctx):
    store, cfg = deps(ctx)
    s = store.find(arg_text(update))
    if not s:
        return await update.message.reply_text("Usage: /complete <id or title>")
    store.update(s["id"], status="Completed")
    if cfg.channel_id:
        await post_card(ctx.bot, cfg, store, s)
        await post_to_channel(ctx.bot, cfg.channel_id, f"✅ <b>{H(s['title'])}</b> is COMPLETE. Binge the whole thing 😈")
    await update.message.reply_text(f"✅ {s['title']} marked completed.")


@admin_only
async def edit(update, ctx):
    store, cfg = deps(ctx)
    p = arg_text(update).split(maxsplit=2)
    fields = {"title", "synopsis", "tags", "heat", "status"}
    if len(p) < 3 or p[1] not in fields or not (s := store.find(p[0])):
        return await update.message.reply_text("Usage: /edit <id> <title|synopsis|tags|heat|status> <value>")
    v = p[2]
    val = [t.strip() for t in v.split(",")] if p[1] == "tags" else int(v) if p[1] == "heat" else v.title() if p[1] == "status" else v
    store.update(s["id"], **{p[1]: val})
    if cfg.channel_id and store.channel_post(s["id"]):
        await post_card(ctx.bot, cfg, store, s)
    await update.message.reply_text(f"✏️ Updated {p[1]}.")


@admin_only
async def delete(update, ctx):
    store, cfg = deps(ctx)
    s = store.find(arg_text(update))
    if not s:
        return await update.message.reply_text("Usage: /delete <id or title>")
    mid = store.channel_post(s["id"])
    if mid and cfg.channel_id:
        try:
            await ctx.bot.delete_message(cfg.channel_id, mid)
        except Exception:
            pass
    store.delete(s["id"])
    await update.message.reply_text(f"🗑 Deleted {s['title']}.")


@admin_only
async def list_cmd(update, ctx):
    store, _ = deps(ctx)
    lines = [f"<code>{s['id']}</code> {H(s['title'])} — {s['status']}, {len(s['episodes'])} eps" for s in store.listing(order="title")]
    await update.message.reply_text("📚 <b>Series</b>\n" + "\n".join(lines or ["(none)"]), parse_mode=HTML)


@admin_only
async def stats(update, ctx):
    store, _ = deps(ctx)
    ss = store.listing()
    await update.message.reply_text(
        f"📊 Series: {len(ss)} (🔄 {sum(s['status']=='Ongoing' for s in ss)} / ✅ {sum(s['status']=='Completed' for s in ss)})\n"
        f"Episodes: {sum(len(s['episodes']) for s in ss)}\nRequests: {len(store.d['requests'])}")


@admin_only
async def post(update, ctx):
    """/post [text] — custom text or a random spicy teaser."""
    store, cfg = deps(ctx)
    if await _need_channel(update, cfg):
        await post_to_channel(ctx.bot, cfg.channel_id, H(arg_text(update)) or random_from(random.choice(["scene", "episode", "dirty"])))
        await update.message.reply_text("✅ Posted to channel.")


@admin_only
async def repost(update, ctx):
    """/repost <id|all> — (re)post series card(s) to the channel."""
    store, cfg = deps(ctx)
    if not await _need_channel(update, cfg):
        return
    a = arg_text(update)
    items = store.listing() if a == "all" else [s for s in [store.find(a)] if s]
    if not items:
        return await update.message.reply_text("Usage: /repost <id|title|all>")
    for s in items:
        store.d["channel_posts"].pop(str(s["id"]), None)
        await post_card(ctx.bot, cfg, store, s)
    await update.message.reply_text(f"📤 Posted {len(items)} card(s).")


@admin_only
async def schedule(update, ctx):
    """/schedule YYYY-MM-DD HH:MM text   (times in TIMEZONE)"""
    store, cfg = deps(ctx)
    p = arg_text(update).split(maxsplit=2)
    try:
        when = dt.datetime.strptime(f"{p[0]} {p[1]}", "%Y-%m-%d %H:%M").replace(tzinfo=cfg.tz)
        text = p[2]
    except Exception:
        return await update.message.reply_text("Usage: /schedule YYYY-MM-DD HH:MM <text>")
    if when <= dt.datetime.now(cfg.tz):
        return await update.message.reply_text("That time is in the past.")
    sc = {"id": len(store.d["schedules"]) + 1, "at": when.timestamp(), "text": H(text), "done": False}
    store.d["schedules"].append(sc); store.save()
    jobs.queue_schedule(ctx.application, sc)
    await update.message.reply_text(f"⏰ Scheduled #{sc['id']}.")


@admin_only
async def schedules(update, ctx):
    store, cfg = deps(ctx)
    rows = [f"#{s['id']} {dt.datetime.fromtimestamp(s['at'], cfg.tz):%Y-%m-%d %H:%M} — {s['text'][:40]}"
            for s in store.d["schedules"] if not s["done"]]
    await update.message.reply_text("⏰ Pending:\n" + "\n".join(rows) if rows else "No pending schedules.")


@admin_only
async def digest(update, ctx):
    ok = await jobs.daily_digest(ctx)
    await update.message.reply_text("📅 Digest posted." if ok else "No new episodes in the last 24h.")


@admin_only
async def admin_help(update, ctx):
    await update.message.reply_text(
        "🛠 <b>Admin</b>\n/add Title | Tropes | heat | synopsis\n/addep &lt;id&gt; + newline + episode text\n"
        "/complete &lt;id&gt;\n/edit &lt;id&gt; &lt;field&gt; &lt;value&gt;\n/delete &lt;id&gt;\n/list, /stats\n"
        "/repost &lt;id|all&gt; — post series cards\n/post [text] — teaser/custom post\n"
        "/poster &lt;id&gt; [url|gen|-] or send a photo\n/schedule YYYY-MM-DD HH:MM text, /schedules\n/digest — post today's drops now\n/cancel — abort current step", parse_mode=HTML)


POSTER_DIR = ROOT / "data" / "posters"


async def _apply_poster(update, ctx, s, value):
    store, cfg = deps(ctx)
    st = ctx.bot_data.get("storage")
    if st and st.backend == "telegram" and value.startswith("/"):
        value = await st.upload_poster(open(value, "rb").read())  # keep posters in the DB channel
    store.update(s["id"], poster=value)
    msg = f"🖼 Poster set for {H(s['title'])}."
    if cfg.channel_id and store.channel_post(s["id"]):
        # text card -> photo card needs a repost (heaven-bot does the same)
        try:
            await ctx.bot.delete_message(cfg.channel_id, store.channel_post(s["id"]))
        except Exception:
            pass
        store.d["channel_posts"].pop(str(s["id"]), None)
        try:
            await post_card(ctx.bot, cfg, store, s); msg += " Channel card reposted."
        except Exception as e:
            msg += f" ⚠️ Channel: {H(str(e))}"
    await update.effective_message.reply_text(msg, parse_mode=HTML)


@admin_only
async def poster(update, ctx):
    """/poster <id> [url|gen|-]  — or reply to a photo with /poster <id>, or send the photo next."""
    store, _ = deps(ctx)
    p = arg_text(update).split()
    s = store.find(p[0]) if p else None
    if not s:
        return await update.message.reply_text("Usage: /poster <id> [image URL | gen | -]\nOr reply to a photo with /poster <id>, or send /poster <id> then the photo.")
    if len(p) > 1:
        if p[1] == "-":
            store.update(s["id"], poster=None)
            return await update.message.reply_text("Poster removed (text card fallback).")
        if p[1] == "gen":
            return await _apply_poster(update, ctx, s, str(make_poster(s, POSTER_DIR)))
        return await _apply_poster(update, ctx, s, p[1])
    r = update.message.reply_to_message
    if r and r.photo:
        return await _apply_poster(update, ctx, s, r.photo[-1].file_id)
    ctx.user_data["wizard"] = ("poster", s["id"])
    await update.message.reply_text(f"📸 Send the poster photo for {s['title']} (or /cancel).",
                                    reply_markup=M([[B("✖️ Cancel", callback_data="cancel")]]))


async def on_photo(update, ctx):
    w = ctx.user_data.get("wizard")
    if not w or w[0] != "poster" or update.effective_user.id not in ctx.bot_data["config"].admin_ids:
        return
    ctx.user_data.pop("wizard", None)
    store, _ = deps(ctx)
    if s := store.get(w[1]):
        await _apply_poster(update, ctx, s, update.message.photo[-1].file_id)


def handlers():
    return [CommandHandler(n, f) for n, f in [
        ("add", add), ("addep", addep), ("complete", complete), ("edit", edit), ("delete", delete),
        ("list", list_cmd), ("stats", stats), ("post", post), ("repost", repost), ("schedule", schedule),
        ("schedules", schedules), ("digest", digest), ("admin", admin_help), ("poster", poster)]] + \
        [MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo)]
