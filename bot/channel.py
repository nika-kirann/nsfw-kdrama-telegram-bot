"""Channel posting: series cards with deep-link buttons (ported from heaven-bot's card + private browsing pattern)."""
import html
import logging

from telegram import Bot, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.constants import ParseMode
from telegram.error import TelegramError

log = logging.getLogger(__name__)
H = html.escape


def heat(n):
    return "🌶" * n


def series_card(s, brand="") -> str:
    status = "✅ COMPLETED" if s["status"] == "Completed" else "🔄 ONGOING"
    tags = " ".join("#" + t.replace(" ", "") for t in s["tags"])
    return (f"🔞 <b>{H(s['title'])}</b>\n"
            f"┌ Status: {status}\n├ Episodes: {len(s['episodes'])}\n└ Heat: {heat(s['heat'])}\n\n"
            f"{tags}\n\n<blockquote expandable>{H(s['synopsis'])}</blockquote>\n"
            f"<i>Fictional adults only · 18+</i>" + (f"\n\nPowered by {H(brand)}" if brand else ""))


def card_buttons(s, bot_username) -> M:
    n = len(s["episodes"])
    return M([[B(f"🔥 Read episodes · {n} EP", url=f"https://t.me/{bot_username}?start=s_{s['id']}")],
              [B("💌 Request story", url=f"https://t.me/{bot_username}?start=request"),
               B("🔎 Browse", url=f"https://t.me/{bot_username}?start=browse")]])


async def post_to_channel(bot: Bot, channel_id: str, text: str, markup=None):
    return await bot.send_message(chat_id=channel_id, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def post_card(bot, cfg, store, s):
    """Post (or re-edit) a series card in the channel."""
    me = await bot.get_me()
    text, mk = series_card(s, cfg.brand), card_buttons(s, me.username)
    mid = store.channel_post(s["id"])
    photo = store.poster_input(s)
    if mid:
        try:
            if photo:
                await bot.edit_message_caption(cfg.channel_id, mid, caption=text, parse_mode=ParseMode.HTML, reply_markup=mk)
            else:
                await bot.edit_message_text(text, cfg.channel_id, mid, parse_mode=ParseMode.HTML, reply_markup=mk)
            return mid
        except TelegramError as e:
            log.info("edit failed (%s), reposting", e)
    if photo:
        msg = await bot.send_photo(cfg.channel_id, photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=mk)
    else:
        msg = await post_to_channel(bot, cfg.channel_id, text, mk)
    store.set_channel_post(s["id"], msg.message_id)
    return msg.message_id


async def announce_episode(bot, cfg, s, n):
    me = await bot.get_me()
    teaser = H(s["episodes"][n - 1]["text"][:180]) + "…"
    await post_to_channel(bot, cfg.channel_id,
                          f"🆕 <b>{H(s['title'])}</b> — EP {n} just dropped {heat(s['heat'])}\n\n<i>{teaser}</i>",
                          M([[B(f"🔥 Read EP {n}", url=f"https://t.me/{me.username}?start=e_{s['id']}_{n}")]]))
