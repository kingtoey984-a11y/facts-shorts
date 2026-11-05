"""Hologram / X-ray channel DNA: colour grade + HUD overlay layers.

The overlay is drawn as a transparent 1080x1920 PNG per shot and composited by ffmpeg,
so every clip shares the same look: dark cyan grade, corner brackets, scanlines,
glowing callout rings, leader-line labels, rulers and big counters.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
CYAN = (47, 230, 255)
YELLOW = (255, 214, 10)
WHITE = (240, 252, 255)

# ffmpeg grade: lift to teal shadows, cool mids, lower saturation, contrast, vignette
# Filtergraph fragment (needs one input and gives one output): x-ray duotone mixed with
# the original, plus bloom so highlights glow like a hologram.
GRADE = ("format=gbrp,split=2[ga][gb];"
         "[gb]hue=s=0,format=gbrp,curves=r='0/0 0.4/0.08 0.75/0.5 1/0.9'"
         ":g='0/0.02 0.4/0.36 0.75/0.84 1/1':b='0/0.07 0.4/0.5 0.75/0.95 1/1'[gd];"
         "[gd][ga]blend=all_mode=normal:all_opacity=0.8,split=2[gc][ge];"
         "[ge]gblur=sigma=18,curves=all='0/0 0.6/0.08 1/0.55'[gg];"
         "[gc][gg]blend=all_mode=screen,eq=contrast=1.05:gamma=1.12,vignette=PI/5,format=yuv420p")

_FONT_CANDIDATES = {
    "bold": ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "mono": ["DejaVuSansMono-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"],
    "display": [str(Path(__file__).resolve().parent.parent / "assets/fonts/Anton-Regular.ttf"),
                "/usr/share/fonts/opentype/inter/Inter-Black.otf", "DejaVuSans-Bold.ttf"],
}


def font(kind, size):
    for f in _FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _glow(layer, radius=10, strength=2):
    blur = layer.filter(ImageFilter.GaussianBlur(radius))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    for _ in range(strength):
        out = Image.alpha_composite(out, blur)
    return Image.alpha_composite(out, layer)


def scanlines(alpha=18):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(0, H, 4):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, alpha), width=1)
    return im


def brackets(d, inset=56, length=90, width=5, color=CYAN):
    c = color + (230,)
    for (x, y, sx, sy) in [(inset, inset, 1, 1), (W - inset, inset, -1, 1),
                           (inset, H - inset, 1, -1), (W - inset, H - inset, -1, -1)]:
        d.line([(x, y), (x + sx * length, y)], fill=c, width=width)
        d.line([(x, y), (x, y + sy * length)], fill=c, width=width)


def tag(d, text, x=90, y=96):
    f = font("mono", 34)
    d.ellipse([x, y + 8, x + 22, y + 30], fill=YELLOW + (255,))
    d.text((x + 38, y), text, font=f, fill=WHITE + (235,))
    tw = d.textlength(text, font=f)
    d.line([(x, y + 52), (x + 38 + tw, y + 52)], fill=CYAN + (200,), width=3)


def ring(d, x, y, r=90, color=CYAN):
    c = color + (255,)
    d.ellipse([x - r, y - r, x + r, y + r], outline=c, width=6)
    d.ellipse([x - r - 22, y - r - 22, x + r + 22, y + r + 22], outline=color + (110,), width=3)
    for a in (0, 90, 180, 270):  # tick marks
        import math
        dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
        d.line([(x + dx * (r + 30), y + dy * (r + 30)), (x + dx * (r + 52), y + dy * (r + 52))],
               fill=c, width=5)


def label(d, text, from_xy, to_xy, sub=None, color=CYAN):
    (x1, y1), (x2, y2) = from_xy, to_xy
    c = color + (255,)
    d.line([(x1, y1), (x2, y2)], fill=c, width=4)
    right = x2 >= x1
    f = font("display", 64)
    tw = d.textlength(text, font=f)
    tx = x2 + 10 if right else x2 - tw - 10
    tx = max(60, min(tx, W - 60 - tw))
    d.line([(min(x2, tx), y2), (max(x2, tx + tw), y2)], fill=c, width=4)
    d.ellipse([x2 - 9, y2 - 9, x2 + 9, y2 + 9], fill=c)
    d.text((tx, y2 - 78), text, font=f, fill=WHITE + (255,), stroke_width=3, stroke_fill=(0, 20, 30, 255))
    if sub:
        fs = font("mono", 30)
        sw = d.textlength(sub, font=fs)
        sx = max(60, min(x2 + 10 if right else x2 - sw - 10, W - 60 - sw))
        d.text((sx, y2 + 12), sub, font=fs, fill=color + (230,))


def ruler(d, x, y1, y2, text, color=YELLOW):
    c = color + (255,)
    d.line([(x, y1), (x, y2)], fill=c, width=5)
    for i, y in enumerate(range(y1, y2 + 1, 30)):
        L = 34 if i % 5 == 0 else 18
        d.line([(x, y), (x + L, y)], fill=c, width=4)
    f = font("display", 120)
    d.text((x + 50, (y1 + y2) // 2 - 80), text, font=f, fill=c, stroke_width=4,
           stroke_fill=(0, 0, 0, 255))


def overlay(spec):
    """spec: dict with optional keys tag, rings[], labels[], ruler, counter."""
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    brackets(d)
    if spec.get("tag"):
        tag(d, spec["tag"])
    for r in spec.get("rings", []):
        ring(d, *r)
    for lb in spec.get("labels", []):
        label(d, lb["text"], tuple(lb["from"]), tuple(lb["to"]), lb.get("sub"))
    if spec.get("ruler"):
        ruler(d, *spec["ruler"])
    glowing = _glow(base, radius=9, strength=2)
    return Image.alpha_composite(scanlines(), glowing)
