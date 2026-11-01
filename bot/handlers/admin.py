"""Admin commands (ported from heaven-bot): /add /addep /complete /edit /delete /list /stats /post /repost
/schedule /schedules /digest /admin."""
import datetime as dt
import random
import re

from telegram.constants import ParseMode
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import CommandHandler, MessageHandler, filters

from .. import jobs
from ..config import ROOT
from ..posters import make_poster
from ..channel import announce_episode, post_card, post_to_channel
from ..content import random_from
from .common import H, LINK_HELP, admin_only, arg_text, deps, describe_links, parse_quality_links

HTML = ParseMode.HTML


async def _need_channel(update, cfg):
    if not cfg.channel_id:
        await update.message.reply_text("CHANNEL_ID not set in .env.")
        return False
    return True


SKIP = "(send /skip to leave it empty)"
CANCEL = M([[B("✖️ Cancel", callback_data="cancel")]])
WIZ_STAGES = ("w_title", "w_tags", "w_heat", "w_syn", "w_status", "w_total", "w_links")


async def _create_series(update, ctx, title, tags, heat_, synopsis, status="Ongoing"):
    store, cfg = deps(ctx)
    s = store.add_series(title, synopsis, tags, status=status, heat=max(1, min(5, heat_)))
    pth = str(make_poster(s, POSTER_DIR))
    st = ctx.bot_data.get("storage")
    if st and st.backend == "telegram":
        try:
            pth = await st.upload_poster(open(pth, "rb").read())
        except Exception as e:
            await update.effective_message.reply_text(f"⚠️ Poster upload to DB channel failed: {H(str(e))}", parse_mode=HTML)
    store.update(s["id"], poster=pth)
    return s


@admin_only
async def add(update, ctx):
    """/add → step-by-step wizard (heaven-bot style). /add Title | tropes | heat | synopsis → quick add, then episodes."""
    raw = arg_text(update)
    if not raw:
        ctx.user_data["wizard"] = ("w_title", {})
        return await update.message.reply_text("🎬 <b>New series</b>\n📝 Send the <b>title</b>.", parse_mode=HTML, reply_markup=CANCEL)
    p = [x.strip() for x in raw.split("|")]
    if len(p) < 4 or not p[2].isdigit():
        return await update.message.reply_text("Usage: /add (wizard) or /add Title | Trope1, Trope2 | heat(1-5) | synopsis")
    s = await _create_series(update, ctx, p[0], [x.strip() for x in p[1].split(",") if x.strip()], int(p[2]), p[3])
    await update.message.reply_text(f"✅ Added #{s['id']} {H(s['title'])}.", parse_mode=HTML)
    await _ask_total(update.message, ctx, {"sid": s["id"], "new": True})


async def _ask_total(msg, ctx, d):
    ctx.user_data["wizard"] = ("w_total", d)
    await msg.reply_text(f"🔢 <b>Total episodes</b> (number) {SKIP}", parse_mode=HTML, reply_markup=CANCEL)


async def _ask_links(msg, ctx, d):
    ctx.user_data["wizard"] = ("w_links", d)
    start = d.get("start", 1)
    await msg.reply_text(f"🔗 <b>Episode links by quality</b>, starting at EP {start}.\n" + LINK_HELP + "\n" + SKIP,
                         parse_mode=HTML, reply_markup=CANCEL, disable_web_page_preview=True)


async def _finish(msg, ctx, d, eps):
    store, cfg = deps(ctx)
    ctx.user_data.pop("wizard", None)
    s = store.get(d["sid"])
    touched = store.apply_links(s["id"], eps, d.get("total")) if (eps or d.get("total")) else []
    lines = [f"✅ <b>{H(s['title'])}</b> (#{s['id']}) saved — {len(s['episodes'])} episode(s).",
             f"🔗 Links: {describe_links(eps)}"]
    if cfg.channel_id:
        try:
            await post_card(ctx.bot, cfg, store, s)
            if touched:
                await announce_episode(ctx.bot, cfg, s, touched[0], touched[-1])
            lines.append("📤 Channel card " + ("updated + drop announced." if touched else "posted."))
        except Exception as e:
            lines.append(f"⚠️ Channel: {H(str(e))}")
    lines.append(f"Add more later: /addep {s['id']} · check: /eps {s['id']} · poster: /poster {s['id']}")
    await msg.reply_text("\n".join(lines), parse_mode=HTML)


async def wizard_text(update, ctx):
    """Text steps of the add/episode wizard (called from viewer.on_text)."""
    if update.effective_user.id not in ctx.bot_data["config"].admin_ids:
        ctx.user_data.pop("wizard", None); return
    stage, d = ctx.user_data["wizard"]
    msg, text = update.message, update.message.text.strip()
    if stage == "w_title":
        d["title"] = text[:120]; ctx.user_data["wizard"] = ("w_tags", d)
        return await msg.reply_text("🏷 <b>Tropes</b>, comma separated (e.g. CEO, Office Romance, Slow Burn) " + SKIP, parse_mode=HTML, reply_markup=CANCEL)
    if stage == "w_tags":
        d["tags"] = [x.strip() for x in text.split(",") if x.strip()]; ctx.user_data["wizard"] = ("w_heat", d)
        return await msg.reply_text("🌶 <b>Heat</b> 1–5", parse_mode=HTML,
                                    reply_markup=M([[B("🌶" * i, callback_data=f"wz:heat:{i}") for i in range(1, 6)], [B("✖️ Cancel", callback_data="cancel")]]))
    if stage == "w_heat":
        if not text.isdigit() or not 1 <= int(text) <= 5:
            return await msg.reply_text("Send 1–5 or tap a button.")
        d["heat"] = int(text); return await _ask_syn(msg, ctx, d)
    if stage == "w_syn":
        d["synopsis"] = text[:900]; return await _ask_status(msg, ctx, d)
    if stage == "w_status":
        return await msg.reply_text("Tap 🔄 Ongoing or ✅ Completed above.")
    if stage == "w_total":
        if not text.isdigit() or not 1 <= int(text) <= 500:
            return await msg.reply_text("Send a number like 16, or /skip.")
        d["total"] = int(text); return await _ask_links(msg, ctx, d)
    if stage == "w_links":
        try:
            eps = parse_quality_links(text, d.get("total"), d.get("start", 1))
        except ValueError as e:
            return await msg.reply_text(f"⚠️ {H(str(e))}. Try again, /skip or /cancel.", parse_mode=HTML)
        return await _finish(msg, ctx, d, eps)


async def _ask_syn(msg, ctx, d):
    ctx.user_data["wizard"] = ("w_syn", d)
    await msg.reply_text("📖 <b>Synopsis</b> (characters are adults 25+) " + SKIP, parse_mode=HTML, reply_markup=CANCEL)


async def _ask_status(msg, ctx, d):
    ctx.user_data["wizard"] = ("w_status", d)
    await msg.reply_text("📡 <b>Status</b>", parse_mode=HTML, reply_markup=M([[B("🔄 Ongoing", callback_data="wz:status:Ongoing"),
                         B("✅ Completed", callback_data="wz:status:Completed")], [B("✖️ Cancel", callback_data="cancel")]]))


async def wizard_cb(update, ctx):
    q = update.callback_query
    w = ctx.user_data.get("wizard")
    if not w or update.effective_user.id not in ctx.bot_data["config"].admin_ids:
        return await q.answer("Wizard expired — start again with /add.", show_alert=True)
    await q.answer()
    _, field, val = q.data.split(":", 2)
    stage, d = w
    if field == "heat" and stage == "w_heat":
        d["heat"] = int(val); await q.edit_message_text(f"Heat: {'🌶' * int(val)}")
        return await _ask_syn(q.message, ctx, d)
    if field == "status" and stage == "w_status":
        await q.edit_message_text(f"Status: {val}")
        s = await _create_series(update, ctx, d["title"], d.get("tags", []), d.get("heat", 3), d.get("synopsis", ""), val)
        return await _ask_total(q.message, ctx, {"sid": s["id"], "new": True})


async def skip(update, ctx):
    w = ctx.user_data.get("wizard")
    if not w or w[0] not in WIZ_STAGES or update.effective_user.id not in ctx.bot_data["config"].admin_ids:
        return await update.message.reply_text("Nothing to skip.")
    stage, d = w
    msg = update.message
    if stage == "w_title":
        return await msg.reply_text("Title is required (or /cancel).")
    if stage == "w_tags":
        d["tags"] = []; ctx.user_data["wizard"] = ("w_heat", d)
        return await msg.reply_text("🌶 <b>Heat</b> 1–5", parse_mode=HTML, reply_markup=M([[B("🌶" * i, callback_data=f"wz:heat:{i}") for i in range(1, 6)]]))
    if stage == "w_heat":
        d["heat"] = 3; return await _ask_syn(msg, ctx, d)
    if stage == "w_syn":
        d["synopsis"] = ""; return await _ask_status(msg, ctx, d)
    if stage == "w_status":
        return await msg.reply_text("Tap Ongoing or Completed.")
    if stage == "w_total":
        return await _ask_links(msg, ctx, d)
    if stage == "w_links":
        return await _finish(msg, ctx, d, {})


ADDEP_HELP = ("Usage:\n/addep &lt;id&gt; — wizard: total episodes, then links by quality\n"
              "/addep &lt;id&gt; + links (same formats) — one-shot, starts at first episode without links\n"
              "/setep &lt;id&gt; &lt;ep&gt; + links — replace one episode's links\n\n" + LINK_HELP)


async def _announce(ctx, cfg, store, s, n, upto=None):
    if not cfg.channel_id:
        return ""
    try:
        await post_card(ctx.bot, cfg, store, s); await announce_episode(ctx.bot, cfg, s, n, upto)
        return " Card updated + drop announced."
    except Exception as e:
        return f" ⚠️ Channel: {H(str(e))}"


def _split_ref(store, raw):
    """'/addep <id|title> [links…]' → (series, links_text)."""
    first, _, rest = raw.partition("\n")
    ref, _, inline = first.strip().partition(" ")
    s = store.find(ref)
    if not s and "://" not in first:
        s, inline = store.find(first), ""
    return s, (inline + "\n" + rest).strip()


@admin_only
async def addep(update, ctx):
    store, cfg = deps(ctx)
    s, body = _split_ref(store, arg_text(update))
    if not s:
        return await update.message.reply_text(ADDEP_HELP, parse_mode=HTML, disable_web_page_preview=True)
    start = next((e["n"] for e in s["episodes"] if not e.get("links")), len(s["episodes"]) + 1)
    if not body:
        await update.message.reply_text(f"📺 <b>{H(s['title'])}</b> — {len(s['episodes'])} episode(s), next without link: EP {start}.", parse_mode=HTML)
        return await _ask_total(update.message, ctx, {"sid": s["id"], "start": start})
    try:
        eps = parse_quality_links(body, None, start)
    except ValueError as e:
        return await update.message.reply_text(f"⚠️ {H(str(e))}", parse_mode=HTML)
    touched = store.apply_links(s["id"], eps)
    msg = f"🔗 {H(s['title'])}: {describe_links(eps)} saved." + await _announce(ctx, cfg, store, s, touched[0], touched[-1])
    await update.message.reply_text(msg, parse_mode=HTML)


@admin_only
async def setep(update, ctx):
    """/setep <id> <ep> + links — replace an episode's watch links."""
    store, cfg = deps(ctx)
    first, _, rest = arg_text(update).partition("\n")
    parts = first.split(maxsplit=2)
    s = store.find(parts[0]) if parts else None
    if not s or len(parts) < 2 or not parts[1].isdigit() or not 1 <= int(parts[1]) <= len(s["episodes"]):
        return await update.message.reply_text(ADDEP_HELP, parse_mode=HTML, disable_web_page_preview=True)
    n = int(parts[1])
    try:
        eps = parse_quality_links(((parts[2] if len(parts) > 2 else "") + "\n" + rest).strip(), None, n)
    except ValueError as e:
        return await update.message.reply_text(f"⚠️ {H(str(e))}", parse_mode=HTML)
    store.apply_links(s["id"], {n: eps.get(n, [])})
    msg = f"🔗 EP {n} of {H(s['title'])} updated." + await _announce(ctx, cfg, store, s, n)
    await update.message.reply_text(msg, parse_mode=HTML)


@admin_only
async def eps(update, ctx):
    """/eps <id> — list episodes with their link status."""
    store, _ = deps(ctx)
    s = store.find(arg_text(update))
    if not s:
        return await update.message.reply_text("Usage: /eps &lt;id&gt;", parse_mode=HTML)
    rows = [f"EP {e['n']} {H(e.get('title',''))}: " + (", ".join(f'<a href="{H(l["url"])}">{H(l["q"])}{"" if l["kind"] == "part" else "↺"}</a>' for l in e["links"]) or "⏳ no link")
            for e in s["episodes"]]
    await update.message.reply_text(f"<b>{H(s['title'])}</b>\n" + ("\n".join(rows) or "No episodes."),
                                    parse_mode=HTML, disable_web_page_preview=True)


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
        "🛠 <b>Admin</b>\n/add — wizard (title → tropes → heat → synopsis → status → total eps → links)\n/add Title | Tropes | heat | synopsis — quick add, then episode wizard\n/addep &lt;id&gt; — episode wizard, or /addep &lt;id&gt; + links one-shot\n/skip — skip a wizard step\n/setep &lt;id&gt; &lt;ep&gt; &lt;links&gt; — replace links\n/eps &lt;id&gt; — episode link status\n"
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
        ("add", add), ("addep", addep), ("setep", setep), ("eps", eps), ("complete", complete), ("edit", edit), ("delete", delete),
        ("list", list_cmd), ("stats", stats), ("post", post), ("repost", repost), ("schedule", schedule),
        ("schedules", schedules), ("digest", digest), ("admin", admin_help), ("skip", skip), ("poster", poster)]] + \
        [MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo)]
