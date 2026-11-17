#!/usr/bin/env python3
"""Render the hen mark from the system's Noto Color Emoji font.

Writes public/hen.png (blue, for the web app) and label_templates/marks/hen.png (1-bit, for thermal printers).
Needs Pillow and a Noto Color Emoji font. The outputs are committed, so this only matters if you want to change the mark.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT = next((p for p in ("/usr/share/fonts/noto/NotoColorEmoji.ttf", "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf") if Path(p).exists()), None)
GLYPH = sys.argv[1] if len(sys.argv) > 1 else "\U0001F414"  # chicken
ROOT = Path(__file__).resolve().parent.parent

if not FONT:
    sys.exit("Noto Color Emoji font not found")
im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
ImageDraw.Draw(im).text((10, 10), GLYPH, font=ImageFont.truetype(FONT, 109), embedded_color=True)
im = im.crop(im.getbbox())

# blue version for the app header
gray = ImageOps.grayscale(im)
blue = ImageOps.colorize(ImageOps.autocontrast(gray), black=(40, 100, 200), white=(190, 220, 255)).convert("RGBA")
blue.putalpha(im.getchannel("A"))
(ROOT / "public").mkdir(exist_ok=True)
blue.resize((blue.width * 64 // blue.height, 64), Image.LANCZOS).save(ROOT / "public" / "hen.png")

# 1-bit version for labels: dithered shading inside a solid outline, so it still reads at ~8 mm on a thermal printer
from PIL import ImageChops, ImageFilter
alpha = im.getchannel("A").point(lambda v: 255 if v > 100 else 0)
flat = Image.new("RGB", im.size, "white"); flat.paste(im, mask=im.getchannel("A"))
shade = ImageOps.autocontrast(ImageOps.grayscale(flat)).point(lambda v: min(255, int(v * 0.55) + 110))  # lighten so fill stays airy
dith = shade.convert("1")  # Floyd-Steinberg
outline = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(5)), alpha.filter(ImageFilter.MinFilter(3)))
mono = Image.new("L", im.size, 255)
mono.paste(dith.convert("L"), mask=alpha)
mono.paste(0, mask=outline.point(lambda v: 255 if v > 0 else 0))
mono = mono.convert("1")
out = ROOT / "label_templates" / "marks"; out.mkdir(parents=True, exist_ok=True)
mono.resize((mono.width * 120 // mono.height, 120), Image.NEAREST).save(out / "hen.png", optimize=True)
print("wrote public/hen.png and label_templates/marks/hen.png")
