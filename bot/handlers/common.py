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


URL_RE = re.compile(r"^https?://\S+$", re.I)
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +._-]{0,11}$")
INLINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 +._-]{0,11}?)\s*[:=]\s*(.*)$")


def norm_quality(label: str) -> str:
    label = label.strip()
    if re.fullmatch(r"\d{3,4}[pP]", label):
        return label.lower()
    if re.fullmatch(r"\d{3,4}", label):
        return label + "p"
    return label.upper() if len(label) <= 3 else label


def parse_quality_links(text: str, total: int | None = None, start: int = 1) -> dict[int, list[tuple[str, str, str]]]:
    """Parse episode links grouped by quality. Returns {ep: [(quality, url, kind), ...]}.

    Accepted (mixable):
      480p: url1, url2            one line = one episode; comma-separated URLs = parts of that episode
      720p: urlA | urlB           ' | ' separated URLs = mirrors of the same episode
      1080p                       block header; each following URL line = next episode in that quality
      1080p: https://x/{ep}.mkv 1 16   pattern per quality (start/end optional; end defaults to total)
      https://x/1.mp4             legacy, no quality -> 'HD'
      EP 9                        following links start at episode 9
    Each quality numbers its episodes independently, starting at `start`."""
    text = (text or "").strip()
    if not text or text.lower() in {"skip", "none", "-", "/skip"}:
        return {}
    out: dict[int, list] = {}
    nxt: dict[str, int] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        content = line
        m = re.fullmatch(r"(?:ep|episode|start)\s*[:#]?\s*(\d+)", line, re.I)
        if m:  # 'EP 9' line: following links (all qualities) start at episode 9
            start, nxt = int(m.group(1)), {}
            continue
        if not line.lower().startswith(("http://", "https://")):
            m = INLINE_RE.match(line)
            if m:
                current, content = norm_quality(m.group(1)), m.group(2).strip()
                if not content:
                    continue
            elif LABEL_RE.match(line) and "://" not in line:
                current = norm_quality(line)
                continue
            else:
                raise ValueError(f"Can't read this line: {line[:60]}")
        q = current or "HD"
        if "{ep}" in content:
            parts = content.split()
            pattern = parts[0]
            s = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else nxt.get(q, start)
            e = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else (total or s)
            if not URL_RE.match(pattern.replace("{ep}", "1")):
                raise ValueError("Pattern must be an http(s) URL containing {ep}")
            if e < s:
                raise ValueError(f"{q}: end episode {e} is lower than start {s}")
            for n in range(s, e + 1):
                out.setdefault(n, []).append((q, pattern.replace("{ep}", str(n)), "part"))
            nxt[q] = e + 1
            continue
        if "|" in content:
            urls, kind = [u.strip() for u in content.split("|")], "mirror"
        else:
            urls, kind = [u.strip() for u in re.split(r"[,\s]+", content)], "part"
        urls = [u for u in urls if u]
        bad = [u for u in urls if not URL_RE.match(u)]
        if bad or not urls:
            raise ValueError(f"Not a valid http(s) link: {(bad or [content])[0][:60]}")
        n = nxt.get(q, start)
        out.setdefault(n, []).extend((q, u, kind) for u in urls)
        nxt[q] = n + 1
    if not out:
        raise ValueError("No valid http(s) link found")
    return out



LINK_HELP = (
    "<b>Format</b> (mix freely, one episode per line inside a quality):\n"
    "<code>480p: https://a/ep1.mp4</code>\n"
    "<code>720p: https://b/ep1-part1, https://b/ep1-part2</code>  ← parts\n"
    "<code>1080p: https://c/ep1 | https://mirror/ep1</code>  ← mirrors\n"
    "<code>1080p: https://ex.com/{ep}.mkv 1 16</code>  ← pattern (start end)\n"
    "or a block: a line <code>720p</code> then one URL line per episode.\n"
    "Plain URLs without a quality are saved as HD. Defaults: 480p / 720p / 1080p, any label works.\n"
    "A line <code>EP 5</code> makes the following links start at episode 5.")


def describe_links(eps: dict) -> str:
    if not eps:
        return "no links"
    quals = []
    for links in eps.values():
        for q, _, _ in links:
            if q not in quals:
                quals.append(q)
    nums = sorted(eps)
    rng = f"EP {nums[0]}" if len(nums) == 1 else f"EP {nums[0]}–{nums[-1]}"
    return f"{rng} ({', '.join(quals)})"


def qualities(e):
    out = []
    for l in e.get("links") or []:
        if l["q"] not in out:
            out.append(l["q"])
    return out


def ep_buttons(e):
    """URL buttons: one row per quality; parts -> 'P1 P2', mirrors -> 'M2 M3'."""
    from telegram import InlineKeyboardButton as B
    rows = []
    for q in qualities(e):
        ls = [l for l in e["links"] if l["q"] == q]
        if len(ls) == 1:
            rows.append([B(f"▶️ {q}", url=ls[0]["url"])])
            continue
        row = []
        for i, l in enumerate(ls, 1):
            tag = f"Part {i}" if l["kind"] == "part" else ("" if i == 1 else f"Mirror {i}")
            row.append(B(f"▶️ {q} {tag}".strip(), url=l["url"]))
        rows += [row[i:i + 3] for i in range(0, len(row), 3)]
    return rows
