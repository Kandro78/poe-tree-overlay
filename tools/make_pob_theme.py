"""Build the files of the Path of Building theme (treeoverlay/pob_theme):

* Fonts/Liberation Sans[ Bold].<size>.tga + .tgf: PoB's UI font ("VAR" /
  "VAR BOLD") redrawn with Inter (tools/fonts, SIL Open Font License), in
  PoB's own bitmap font format: per size a white RGBA atlas with the glyphs in
  alpha, and a table "GLYPH x y width left right" for ASCII 0-127, every glyph
  one font height tall on a shared baseline. Each size is fitted to PoB's
  own font (tools/fonts/pob/*.tgf, from PoB's install): PoB lays out labels
  and columns by fixed widths, so text that runs wider than Liberation Sans
  spills over the edges ("lovement Speed Modifier").
* Assets/PoETreeOverlay_round.png: a white disc, drawn as 9 slices for
  rounded boxes.

    python tools/make_pob_theme.py      (needs Pillow)
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "treeoverlay" / "pob_theme"
FONTS = ROOT / "tools" / "fonts"
SIZES = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48, 56, 64]
# what the fit is measured on: PoB's labels and numbers
SAMPLE = ("Movement Speed Modifier Enemy Life Recovery Curses and Debuffs Block Stun Duration "
          "Effective Hit Pool Lightning Max Hit Average Damage Total Increased Configuration "
          "Seething Divine Life Flask, Jingling Spirit Shield 1,755 (+40%) 3,739.9 DPS x 0.81 12.5s")
FIT = 0.97        # at most this wide against PoB's font, over SAMPLE


def pob_advances(name):
    """PoB's own font: per size the advance (width + left + right) of each glyph."""
    out, h = {}, None
    for line in (FONTS / "pob" / f"{name}.tgf").read_text().splitlines():
        m = re.match(r"HEIGHT (\d+);", line)
        if m:
            h = int(m.group(1))
            out[h] = []
            continue
        m = re.match(r"GLYPH\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+);", line)
        if m:
            _, _, w, lft, rgt = map(int, m.groups())
            out[h].append(w + lft + rgt)
    return out


def pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def fitted_advances(font, pob):
    """Inter's advances, spaced so SAMPLE is as wide as FIT times PoB's font
    (whole pixels per glyph, so the spacing is scaled rather than offset: an
    offset rounds the same way for every glyph); none more than 1 px wider
    than PoB's either."""
    def advances(k):
        return [min(round(font.getlength(chr(c)) * k), pob[c] + 1) if 32 <= c < 127 else 0
                for c in range(128)]
    target = FIT * sum(pob[ord(c)] for c in SAMPLE)
    k = 1.15
    while k > 0.75:
        adv = advances(k)
        if sum(adv[ord(c)] for c in SAMPLE) <= target:
            return adv
        k -= 0.0025
    return adv


def make_size(path, height, pob):
    # the same cap height and baseline as Liberation Sans in the same cell, so
    # text keeps its size and place in PoB (Inter's line metrics are taller)
    em = round(0.88 * height)
    font = ImageFont.truetype(str(path), em)
    baseline = round(0.81 * height)
    gap = max(2, height // 4)
    advances = fitted_advances(font, pob)
    glyphs = []
    for code in range(128):
        ch = chr(code)
        adv = advances[code]
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


def make_font(ttf, name):
    pob = pob_advances(name)
    table = []
    for h in SIZES:
        atlas, lines = make_size(FONTS / ttf, h, pob[h])
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
    make_font("Inter-Regular.ttf", "Liberation Sans")
    make_font("Inter-SemiBold.ttf", "Liberation Sans Bold")
    make_round()
    print("written to", OUT)
