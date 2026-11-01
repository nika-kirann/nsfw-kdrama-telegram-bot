# 🔞 Spicy K-Drama Telegram Bot

Adult (18+) K-drama style romance/erotica bot. All characters are fictional consenting adults.
Stack: Python 3.10+, python-telegram-bot v21 (async, polling).

## Setup
1. Create a bot with @BotFather, copy the token.
2. Add the bot as **admin** of your channel (with "Post messages").
3. `cp .env.example .env` and fill:
   - `TELEGRAM_BOT_TOKEN=123:ABC...`
   - `CHANNEL_ID=@yourchannel` (or numeric `-100...` for private channels)
   - `ADMIN_IDS=111111111` (your user ID — get it from @userinfobot)
4. Install & run:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m bot
```

## Commands
**Viewers:** /start (18+ gate, deep links `?start=s_<id>` / `e_<id>_<n>` / `request` / `browse`), /browse (Latest, Hottest, Ongoing, Completed, Tropes, Search, Spicy Scene, Dirty Talk, Character RP, Request), /latest, /search, /scene, /episode, /dirty, /rp, /stop, /request. Any DM text = search.

**Admins:** /add Title | Tropes | heat | synopsis · /addep <id> + newline + text (updates card, announces drop) · /complete · /edit · /delete · /list · /stats · /repost <id|all> · /post [text] · /schedule YYYY-MM-DD HH:MM text · /schedules · /digest · /admin

Channel cards carry "🔥 Read episodes" / "💌 Request" / "🔎 Browse" buttons that open the bot privately. Daily digest at DAILY_DIGEST_TIME (TIMEZONE). Data lives in `data/series.json` (seeded with 3 series).

## Extending
- Seed series: `bot/content/series_seed.py`; quick hits: `scenes.py`, `episodes.py`, `dirty_talk.py`, `characters.py` (HTML formatting).
- `on_text` in `bot/handlers/viewer.py` uses canned RP replies — swap in an LLM call for live roleplay.

## Cancel & posters
- `/cancel` (or the ✖️ Cancel button) clears any pending search, request, roleplay or admin poster step.
- Posters: `data/posters/series_<id>.jpg`, generated with Pillow (`bot/posters.py`, typographic, no faces). Cards are sent as photo + caption when a poster exists, text otherwise. `/add` auto-generates one.
- Admin: `/poster <id> <url>`, `/poster <id> gen` (regenerate), `/poster <id> -` (remove), reply to a photo with `/poster <id>`, or `/poster <id>` then send a photo.

## Channel as database
Set `STORAGE_BACKEND=telegram` and `DB_CHANNEL_ID=-100…` (a **private** channel; add the bot as admin with Post, Edit, Delete and **Pin** messages).
- Startup: the pinned `spicy-backup.json` is downloaded and loaded (no pin → seed data, and a first backup is pinned).
- Every change (add/addep/edit/poster/requests…) uploads a fresh backup ~3 s later, replacing the pinned doc. Final flush on shutdown.
- Posters are uploaded to the DB channel and stored as Telegram file_ids, so they survive redeploys.
- Don't unpin/delete the backup. Run only **one** instance per token (stop the local bot before deploying).

## Deploy on Koyeb (free web service)
The bot long-polls Telegram and, when `PORT` is set, serves `GET /healthz` (200 `{"ok": true}`) so Koyeb treats it as a web service.
1. Push this repo to GitHub (done: `nika-kirann/nsfw-kdrama-telegram-bot`, private).
2. Koyeb → **Secrets**: `TELEGRAM_BOT_TOKEN`, `CHANNEL_ID`, `DB_CHANNEL_ID`, `ADMIN_IDS`.
3. **Create Service → Web service → GitHub** repo, branch `main`, builder **Dockerfile**, instance **Free**, region Frankfurt.
   Port **8000 HTTP**, route `/`, health check HTTP `/healthz`. Env: the 4 secrets + `STORAGE_BACKEND=telegram`, `PORT=8000`, `TIMEZONE=Asia/Kolkata` (see `koyeb.yaml`).
4. Logs should show `Health server listening…`, `DB channel: …`, `Logged in as @…`, `Application started`.
5. Free instances sleep after 1 h without HTTP traffic: add an **UptimeRobot** HTTP monitor on `https://<app>.koyeb.app/healthz` every 5 min.
6. **Stop the local/box bot first** — two pollers on one token conflict.
