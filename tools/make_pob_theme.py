"""Build the files of the Path of Building theme (treeoverlay/pob_theme):

* Fonts/Liberation Sans[ Bold].<size>.tga + .tgf: PoB's UI font ("VAR" /
  "VAR BOLD") redrawn with Inter (tools/fonts, SIL Open Font License), in
  PoB's own bitmap font format: per size a white RGBA atlas with the glyphs in
  alpha, and a table "GLYPH x y width left right" for ASCII 0-127, every glyph
  one font height tall on a shared baseline.
* Assets/PoETreeOverlay_round.png: a white disc, drawn as 9 slices for
  rounded boxes.

    python tools/make_pob_theme.py      (needs Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "treeoverlay" / "pob_theme"
FONTS = ROOT / "tools" / "fonts"
SIZES = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48, 56, 64]


def pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def make_size(path, height, tracking=0.0):
    # the same cap height and baseline as Liberation Sans in the same cell, so
    # text keeps its size and place in PoB (Inter's line metrics are taller)
    em = round(0.88 * height)
    font = ImageFont.truetype(str(path), em)
    baseline = round(0.81 * height)
    gap = max(2, height // 4)
    glyphs = []
    for code in range(128):
        ch = chr(code)
        adv = round(font.getlength(ch) + tracking * em) if 32 <= code < 127 else 0
        box = font.getbbox(ch, anchor="ls") if 32 < code < 127 else None
        if box is None or box[2] <= box[0]:
            glyphs.append((None, 1, 0, max(0, adv - 1)))
            continue
        left, right = box[0], box[2]
        width = right - left
        cell = Image.new("L", (width, height), 0)
        ImageDraw.Draw(cell).text((-left, baseline), ch, font=font, fill=255, anchor="ls")
        glyphs.append((cell, width, left, adv - left - width))
    # pack into rows
    width = pow2(8 * height)
    x = y = 0
    places = []
    for cell, w, _, _ in glyphs:
        if x + w > width:
            x, y = 0, y + height + gap
        places.append((x, y))
        x += w + gap
    atlas = Image.new("RGBA", (width, pow2(y + height)), (255, 255, 255, 0))
    for (cell, *_), (gx, gy) in zip(glyphs, places):
        if cell is not None:
            alpha = atlas.getchannel("A")
            alpha.paste(cell, (gx, gy))
            atlas.putalpha(alpha)
    lines = [f"HEIGHT {height};"]
    for code, ((_, w, lft, rgt), (gx, gy)) in enumerate(zip(glyphs, places)):
        name = f" ({chr(code)})" if 32 <= code < 127 else ""
        lines.append(f"GLYPH {gx:3d} {gy:3d} {w:2d} {lft:2d} {rgt:2d};\t// {code}{name}")
    return atlas, lines


def make_font(ttf, name, tracking=0.0):
    table = []
    for h in SIZES:
        atlas, lines = make_size(FONTS / ttf, h, tracking)
        atlas.save(OUT / "SimpleGraphic" / "Fonts" / f"{name}.{h}.tga", compression="tga_rle")
        table += lines
    (OUT / "SimpleGraphic" / "Fonts" / f"{name}.tgf").write_text("\n".join(table) + "\n", encoding="ascii", newline="\n")


def make_round():
    n = 64
    big = Image.new("L", (n * 4, n * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, n * 4 - 1, n * 4 - 1), fill=255)
    disc = big.resize((n, n), Image.LANCZOS)
    img = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    img.putalpha(disc)
    img.save(OUT / "Assets" / "PoETreeOverlay_round.png")


if __name__ == "__main__":
    (OUT / "SimpleGraphic" / "Fonts").mkdir(parents=True, exist_ok=True)
    (OUT / "Assets").mkdir(parents=True, exist_ok=True)
    make_font("Inter-Regular.ttf", "Liberation Sans", tracking=-0.035)   # about as wide as Liberation
    make_font("Inter-SemiBold.ttf", "Liberation Sans Bold")
    make_round()
    print("written to", OUT)
