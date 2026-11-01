"""Typographic poster generator (Pillow, adapted from heaven-bot's banner.py): crimson→black gradient,
bokeh glow, title, heat, tropes. Text only, no faces/likenesses."""
import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

W, H = 900, 1260
FONTS = ROOT / "assets" / "fonts"
PALETTES = [((60, 0, 20), (8, 0, 10)), ((80, 10, 50), (10, 0, 20)), ((20, 0, 50), (60, 0, 30)), ((90, 20, 10), (15, 0, 5))]


def _font(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default(size)


def make_poster(s, out_dir: Path) -> Path:
    rnd = random.Random(s["title"])
    top, bot = rnd.choice(PALETTES)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    glow = Image.new("RGB", (W, H))
    g = ImageDraw.Draw(glow)
    for _ in range(14):  # bokeh city lights / rain glow
        x, y, r = rnd.randrange(W), rnd.randrange(int(H * .7)), rnd.randrange(30, 140)
        g.ellipse([x - r, y - r, x + r, y + r], fill=(rnd.randrange(150, 255), rnd.randrange(20, 90), rnd.randrange(60, 160)))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(60)), .5)
    d = ImageDraw.Draw(img)
    for _ in range(90):  # rain streaks
        x, y = rnd.randrange(W), rnd.randrange(H)
        d.line([(x, y), (x - 6, y + 40)], fill=(255, 200, 220), width=1)
    d.text((W // 2, 90), "18+  ADULTS ONLY  ·  K-DRAMA", font=_font("DejaVuSans-Bold.ttf", 30), fill=(255, 170, 190), anchor="mm")
    y = H * .52
    for line in textwrap.wrap(s["title"].upper(), 14):
        d.text((W // 2, y), line, font=_font("DejaVuSerif-Bold.ttf", 92), fill=(255, 245, 248), anchor="mm",
               stroke_width=3, stroke_fill=(70, 0, 25))
        y += 108
    d.text((W // 2, y + 30), "♥ " * s["heat"] + f" HEAT {s['heat']}/5", font=_font("DejaVuSans-Bold.ttf", 40), fill=(255, 80, 110), anchor="mm")
    d.text((W // 2, y + 95), "  ·  ".join(s["tags"][:3]), font=_font("DejaVuSans.ttf", 34), fill=(240, 200, 215), anchor="mm")
    status = "COMPLETED" if s["status"] == "Completed" else "ONGOING"
    d.rounded_rectangle([W // 2 - 150, H - 150, W // 2 + 150, H - 90], 30, outline=(255, 120, 150), width=3)
    d.text((W // 2, H - 120), f"{status} · {len(s['episodes'])} EP", font=_font("DejaVuSans-Bold.ttf", 30), fill=(255, 220, 230), anchor="mm")
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"series_{s['id']}.jpg"
    img.save(p, quality=90)
    return p
