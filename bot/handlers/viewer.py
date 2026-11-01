"""Viewer side: age gate, /start deep links, browse menu (Latest/Ongoing/Completed/Tags/Search/Request),
series cards with paginated episodes, episode reader with Prev/Next, quick spicy modes, character RP."""
import random
from math import ceil

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from ..channel import heat, series_card
from ..content import MODES, random_from
from ..content.characters import CHARACTERS
from .common import H, arg_text, deps, ep_buttons

HTML = ParseMode.HTML
PER = 8
WELCOME = ("🔞 <b>Welcome to Spicy K-Drama</b> 💋\nForbidden glances, hotel corridors, rain kisses… "
           "binge steamy serialized dramas, grab a quick spicy scene, or roleplay with your favorite oppa/noona.")


def main_menu():
    return M([
        [B("🆕 Latest", callback_data="br:latest:0"), B("🔥 Hottest", callback_data="br:hot:0")],
        [B("🔄 Ongoing", callback_data="br:ongoing:0"), B("✅ Completed", callback_data="br:completed:0")],
        [B("🏷 Tropes", callback_data="br:tags:0"), B("🔎 Search", callback_data="br:search:0")],
        [B("🌧 Spicy Scene", callback_data="mode:scene"), B("💋 Dirty Talk", callback_data="mode:dirty")],
        [B("🎭 Character RP", callback_data="rp"), B("💌 Request", callback_data="br:request:0")],
    ])


def series_list(items, page, kind, arg=""):
    pages = max(1, ceil(len(items) / PER))
    rows = [[B(f"{'✅' if s['status'] == 'Completed' else '🔄'} {s['title']} {heat(s['heat'])}", callback_data=f"sr:{s['id']}")]
            for s in items[page * PER:(page + 1) * PER]]
    suf = f":{arg}" if arg else ""
    nav = ([B("⬅️", callback_data=f"br:{kind}:{page-1}{suf}")] if page else []) + [B(f"{page+1}/{pages}", callback_data="noop")] \
        + ([B("➡️", callback_data=f"br:{kind}:{page+1}{suf}")] if page < pages - 1 else [])
    return M(rows + [nav, [B("🏠 Menu", callback_data="br:menu:0")]])


def episodes_kb(s, page=0):
    eps = s["episodes"]; pages = max(1, ceil(len(eps) / 10)); page = min(page, pages - 1)
    rows, row = [], []
    for e in eps[page * 10:(page + 1) * 10]:
        row.append(B(f"{'▶️' if e.get('links') else '⏳'} EP {e['n']}", callback_data=f"ep:{s['id']}:{e['n']}"))
        if len(row) == 5:
            rows.append(row); row = []
    if row:
        rows.append(row)
    if pages > 1:
        rows.append(([B("⬅️", callback_data=f"eps:{s['id']}:{page-1}")] if page else []) + [B(f"{page+1}/{pages}", callback_data="noop")]
                    + ([B("➡️", callback_data=f"eps:{s['id']}:{page+1}")] if page < pages - 1 else []))
    rows.append([B("🏠 Menu", callback_data="br:menu:0")])
    return M(rows)


def episode_view(s, n):
    e = s["episodes"][n - 1]
    if e.get("links"):
        body = "▶️ Tap a button below to watch" + (" (pick a quality)." if len(e["links"]) > 1 else ".")
    else:
        body = "⏳ Watch link coming soon — check back or join the channel for the drop."
    text = f"🔞 <b>{H(s['title'])}</b> — EP {n}/{len(s['episodes'])}\n🎬 {H(e.get('title') or f'Episode {n}')}\n\n{body}"
    nav = ([B("⏮ Prev", callback_data=f"ep:{s['id']}:{n-1}")] if n > 1 else []) + \
          ([B("Next ⏭", callback_data=f"ep:{s['id']}:{n+1}")] if n < len(s["episodes"]) else [])
    return text, M(ep_buttons(e) + ([nav] if nav else []) + [[B("📜 Episodes", callback_data=f"eps:{s['id']}:0"), B("🏠 Menu", callback_data="br:menu:0")]])


CANCEL_KB = M([[B("✖️ Cancel", callback_data="cancel")]])


async def send_card(msg, ctx, s, page=0):
    """Send a series card: photo + caption if a poster exists, text otherwise (heaven-bot dm_card pattern)."""
    store, cfg = deps(ctx)
    text, kb = series_card(s, cfg.brand), episodes_kb(s, page)
    photo = store.poster_input(s)
    if photo:
        try:
            return await msg.get_bot().send_photo(msg.chat_id, photo, caption=text, parse_mode=HTML, reply_markup=kb)
        except Exception:
            pass  # fall back to text
    return await msg.reply_text(text, parse_mode=HTML, reply_markup=kb)


async def show(q, text, kb):
    """Edit in place; photo messages can't become text, so send a new message instead."""
    if q.message.photo:
        return await q.message.reply_text(text, parse_mode=HTML, reply_markup=kb)
    return await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)


def clear_state(ctx):
    """Drop every pending flow: awaiting search/request, RP character, admin wizard."""
    n = 0
    for k in ("awaiting", "char", "wizard"):
        n += ctx.user_data.pop(k, None) is not None
    return n


async def cancel(update, ctx):
    n = clear_state(ctx)
    await update.effective_message.reply_text("✖️ Cancelled." if n else "Nothing to cancel 😉",
                                              reply_markup=main_menu() if ctx.user_data.get("age_ok") else None)


def age_kb(payload=""):
    return M([[B("✅ I'm 18+", callback_data=f"age:yes:{payload}"), B("❌ No", callback_data="age:no:")]])


async def route_payload(msg, ctx, payload):
    """Handle deep links: s_<id>, e_<id>_<n>, request, browse."""
    store, cfg = deps(ctx)
    if payload == "request":
        ctx.user_data["awaiting"] = "request"
        return await msg.reply_text("💌 Which spicy trope/story do you want next? Send it.", reply_markup=CANCEL_KB)
    if payload.startswith("s_") and (s := store.get(payload[2:])):
        return await send_card(msg, ctx, s)
    if payload.startswith("e_"):
        sid, _, n = payload[2:].partition("_")
        s = store.get(sid)
        if s and n.isdigit() and 1 <= int(n) <= len(s["episodes"]):
            t, k = episode_view(s, int(n))
            return await msg.reply_text(t, parse_mode=HTML, reply_markup=k)
    await msg.reply_text(WELCOME, parse_mode=HTML, reply_markup=main_menu())


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    payload = ctx.args[0] if ctx.args else ""
    if not ctx.user_data.get("age_ok"):
        return await update.message.reply_text(
            "🔞 <b>Adults only.</b> This bot contains explicit romantic fiction. All characters are fictional "
            "consenting adults (25+).\nAre you 18 or older?", parse_mode=HTML, reply_markup=age_kb(payload[:50]))
    await route_payload(update.message, ctx, payload)


async def gate(update, ctx):
    if ctx.user_data.get("age_ok"):
        return True
    await update.effective_message.reply_text("🔞 Please /start and confirm you're 18+ first.")
    return False


async def help_cmd(update: Update, ctx):
    await update.message.reply_text(
        "📖 <b>Commands</b>\n/start – menu\n/browse – browse series\n/search &lt;text&gt; – title/trope search\n"
        "/latest – newest drops\n/scene /episode /dirty – quick spicy hits\n/rp – roleplay a character, /stop to end\n"
        "/request – ask for a story\n/cancel – cancel search/request/roleplay/admin step\nAdmins: /admin", parse_mode=HTML)


async def browse(update, ctx):
    if await gate(update, ctx):
        await update.message.reply_text("📺 What are you in the mood for?", reply_markup=main_menu())


async def latest(update, ctx):
    if await gate(update, ctx):
        store, _ = deps(ctx)
        await update.message.reply_text("🆕 Latest drops:", reply_markup=series_list(store.listing(), 0, "latest"))


async def search_cmd(update, ctx):
    if not await gate(update, ctx):
        return
    q = arg_text(update)
    if not q:
        ctx.user_data["awaiting"] = "search"
        return await update.message.reply_text("🔎 Send a title or trope (e.g. CEO, Hotel, Slow Burn).", reply_markup=CANCEL_KB)
    await show_search(update.message.reply_text, ctx, q, 0)


async def show_search(send, ctx, q, page):
    store, _ = deps(ctx)
    items = store.listing(query=q)
    if not items:
        return await send(f"Nothing for “{q}” yet 😢 — request it!", reply_markup=main_menu())
    await send(f"🔎 “{q}” ({len(items)}):", reply_markup=series_list(items, page, "search", q[:30]))


async def request_cmd(update, ctx):
    if await gate(update, ctx):
        ctx.user_data["awaiting"] = "request"
        await update.message.reply_text("💌 Tell us the trope/story you want next.", reply_markup=CANCEL_KB)


def quick(mode):
    async def _h(update, ctx):
        if await gate(update, ctx):
            await update.message.reply_text(random_from(mode), parse_mode=HTML)
    return _h


async def rp_cmd(update, ctx):
    if await gate(update, ctx):
        await update.message.reply_text("🎭 Who do you want tonight?", reply_markup=rp_kb())


def rp_kb():
    return M([[B(c["name"], callback_data=f"char:{k}")] for k, c in CHARACTERS.items()])


async def stop(update, ctx):
    ctx.user_data.pop("char", None)
    await update.message.reply_text("🎬 Scene ended. /browse for more.")


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    store, _ = deps(ctx)
    parts = q.data.split(":")
    kind = parts[0]
    if kind == "noop":
        return await q.answer()
    if kind == "cancel":
        clear_state(ctx)
        await q.answer("Cancelled")
        return await q.edit_message_text("✖️ Cancelled.")
    if kind == "age":
        await q.answer()
        if parts[1] != "yes":
            return await q.edit_message_text("Sorry, adults only. 🙅")
        ctx.user_data["age_ok"] = True
        await q.edit_message_text("✅ Verified. Enjoy responsibly 😈")
        return await route_payload(q.message, ctx, ":".join(parts[2:]))
    if not ctx.user_data.get("age_ok"):
        return await q.answer("Please /start and confirm 18+ first.", show_alert=True)
    await q.answer()
    edit = q.edit_message_text
    if kind == "br":
        sub, page, arg = parts[1], int(parts[2]), ":".join(parts[3:])
        if sub == "menu":
            return await show(q, WELCOME, main_menu())
        if sub == "request":
            ctx.user_data["awaiting"] = "request"
            return await q.message.reply_text("💌 Tell us the trope/story you want next.", reply_markup=CANCEL_KB)
        if sub == "search":
            if arg:
                return await show_search(lambda t, reply_markup: show(q, t, reply_markup), ctx, arg, page)
            ctx.user_data["awaiting"] = "search"
            return await q.message.reply_text("🔎 Send a title or trope.", reply_markup=CANCEL_KB)
        if sub == "tags":
            tags = store.top_tags()
            return await show(q, "🏷 Pick a trope:", M(
                [[B(f"{t} ({n})", callback_data=f"br:tag:0:{t[:30]}")] for t, n in tags] + [[B("🏠 Menu", callback_data="br:menu:0")]]))
        items = {"latest": lambda: store.listing(), "hot": lambda: sorted(store.listing(), key=lambda s: -s["heat"]),
                 "ongoing": lambda: store.listing(status="Ongoing"), "completed": lambda: store.listing(status="Completed"),
                 "tag": lambda: store.listing(tag=arg)}[sub]()
        label = {"latest": "🆕 Latest", "hot": "🔥 Hottest", "ongoing": "🔄 Ongoing", "completed": "✅ Completed"}.get(sub, f"🏷 {arg}")
        return await show(q, f"{label} ({len(items)}):", series_list(items, page, sub, arg))
    if kind == "sr" and (s := store.get(parts[1])):
        return await send_card(q.message, ctx, s)
    if kind == "eps" and (s := store.get(parts[1])):
        if q.message.photo:  # paging on the poster card: just swap buttons
            return await q.edit_message_reply_markup(episodes_kb(s, int(parts[2])))
        return await send_card(q.message, ctx, s, int(parts[2]))
    if kind == "ep" and (s := store.get(parts[1])):
        n = int(parts[2])
        if 1 <= n <= len(s["episodes"]):
            t, k = episode_view(s, n)
            return await show(q, t, k)
    if kind == "mode":
        return await q.message.reply_text(random_from(parts[1]), parse_mode=HTML, reply_markup=main_menu())
    if kind == "rp":
        return await q.message.reply_text("🎭 Who do you want tonight?", reply_markup=rp_kb())
    if kind == "char":
        ctx.user_data["char"] = parts[1]
        return await q.message.reply_text(CHARACTERS[parts[1]]["intro"] + "\n\n<i>(Reply to chat · /stop or /cancel to end)</i>", parse_mode=HTML, reply_markup=CANCEL_KB)


async def on_text(update: Update, ctx):
    if not ctx.user_data.get("age_ok"):
        return await gate(update, ctx)
    store, cfg = deps(ctx)
    awaiting = ctx.user_data.pop("awaiting", None)
    text = update.message.text.strip()
    if awaiting == "request":
        rid = store.add_request(update.effective_user.id, text[:500])
        u = update.effective_user
        for a in cfg.admin_ids:
            try:
                await ctx.bot.send_message(a, f"💌 Request #{rid} from {H(u.full_name)} (<code>{u.id}</code>):\n{H(text[:500])}", parse_mode=HTML)
            except Exception:
                pass
        return await update.message.reply_text("💋 Got it! Sent to the admins.")
    if awaiting == "search":
        return await show_search(update.message.reply_text, ctx, text, 0)
    if char := ctx.user_data.get("char"):
        # Placeholder canned replies. Swap in an LLM call here for live roleplay.
        return await update.message.reply_text(random.choice(CHARACTERS[char]["replies"]), parse_mode=HTML)
    await show_search(update.message.reply_text, ctx, text, 0)


def handlers():
    pv = filters.ChatType.PRIVATE
    return [CommandHandler("start", start), CommandHandler("help", help_cmd), CommandHandler("browse", browse),
            CommandHandler("menu", browse), CommandHandler("latest", latest), CommandHandler("search", search_cmd),
            CommandHandler("request", request_cmd), CommandHandler("rp", rp_cmd), CommandHandler("stop", stop), CommandHandler("cancel", cancel),
            *[CommandHandler(m, quick(m)) for m in MODES],
            CallbackQueryHandler(on_cb), MessageHandler(filters.TEXT & ~filters.COMMAND & pv, on_text)]
