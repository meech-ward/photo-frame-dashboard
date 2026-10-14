#!/usr/bin/env python3
"""Generate original offline landscape artwork; no remote photos or credentials.

These deliberately illustrative sample scenes are our own geometry, not Wes's
family photographs. Pillow is host-only. The badge receives three indexed PNGs;
no Python pixel loop or procedural scenery runs on the device.
"""

from pathlib import Path
import math
import random

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1] / "assets"
SCALE = 3
WIDTH, HEIGHT = 320, 240


def polygon(draw, points, fill):
    draw.polygon([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=fill)


def line(draw, points, fill, width=1):
    draw.line([(round(x * SCALE), round(y * SCALE)) for x, y in points], fill=fill, width=max(1, round(width * SCALE)))


def ellipse(draw, bounds, fill):
    draw.ellipse(tuple(round(value * SCALE) for value in bounds), fill=fill)


def sky(top, bottom):
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT * SCALE):
        t = y / (HEIGHT * SCALE - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        draw.line((0, y, WIDTH * SCALE, y), fill=c)
    return image


def coast():
    image = sky((199, 206, 194), (247, 222, 174))
    draw = ImageDraw.Draw(image)
    ellipse(draw, (222, 40, 272, 90), (248, 225, 176))
    polygon(draw, [(0, 107), (24, 100), (61, 105), (105, 78), (141, 108), (192, 115), (230, 92), (320, 117), (320, 240), (0, 240)], (84, 119, 116))
    polygon(draw, [(0, 127), (50, 115), (89, 118), (131, 126), (206, 122), (320, 132), (320, 240), (0, 240)], (49, 104, 112))
    for i in range(14):
        y = 134 + i * 6
        line(draw, [(0, y), (37, y - 2), (87, y + 2), (123, y), (183, y + 2), (251, y - 1), (320, y + 2)], (109 + i * 3, 155 + i * 2, 147 + i * 2), 0.8)
    polygon(draw, [(0, 189), (45, 179), (89, 183), (127, 167), (149, 158), (141, 181), (193, 191), (252, 209), (320, 220), (320, 240), (0, 240)], (191, 156, 112))
    line(draw, [(0, 188), (47, 180), (92, 183), (129, 169), (147, 159)], (244, 230, 198), 3)
    polygon(draw, [(0, 204), (42, 190), (82, 217), (113, 222), (158, 240), (0, 240)], (32, 58, 57))
    for x, base, h in [(8, 190, 83), (24, 188, 68), (40, 186, 74), (61, 195, 55), (77, 205, 61)]:
        tree(draw, x, base, h, (31, 66, 62))
    return image


def tree(draw, x, base, height, fill):
    line(draw, [(x, base), (x, base - height)], fill, 2)
    for i in range(5):
        y = base - height + i * height * 0.16
        half = height * (0.06 + i * 0.035)
        polygon(draw, [(x, y), (x - half, y + height * 0.24), (x + half, y + height * 0.24)], fill)


def lake():
    image = sky((167, 190, 191), (228, 214, 184))
    draw = ImageDraw.Draw(image)
    polygon(draw, [(0, 109), (18, 91), (52, 88), (73, 99), (108, 76), (151, 102), (190, 86), (230, 96), (263, 82), (320, 108), (320, 240), (0, 240)], (92, 129, 121))
    polygon(draw, [(0, 127), (55, 115), (113, 123), (159, 108), (207, 126), (259, 111), (320, 124), (320, 240), (0, 240)], (39, 86, 81))
    polygon(draw, [(0, 136), (320, 137), (320, 240), (0, 240)], (84, 132, 128))
    for i in range(19):
        y = 143 + i * 5
        line(draw, [(0, y), (80, y + math.sin(i) * 2), (173, y), (237, y + 1), (320, y)], (140, 169, 155), 0.5)
    polygon(draw, [(116, 240), (142, 151), (178, 151), (205, 240)], (127, 89, 58))
    for i in range(11):
        y = 156 + i * i * 0.84
        width = 36 + (y - 151) * 0.59
        line(draw, [(160 - width / 2, y), (160 + width / 2, y)], (204, 164, 119), 2)
    line(draw, [(143, 151), (116, 240)], (221, 177, 127), 2)
    line(draw, [(178, 151), (205, 240)], (221, 177, 127), 2)
    for x, base, h in [(2, 153, 115), (27, 150, 98), (304, 156, 127), (279, 157, 87)]:
        tree(draw, x, base, h, (28, 68, 59))
    return image


def mountain():
    image = sky((139, 177, 192), (225, 219, 180))
    draw = ImageDraw.Draw(image)
    polygon(draw, [(0, 111), (37, 66), (64, 92), (101, 30), (144, 90), (188, 49), (241, 92), (277, 58), (320, 117), (320, 240), (0, 240)], (95, 117, 125))
    polygon(draw, [(61, 91), (101, 30), (131, 72), (113, 66), (104, 78), (95, 59), (83, 84)], (217, 222, 213))
    polygon(draw, [(157, 82), (188, 49), (215, 78), (194, 70), (188, 81), (179, 70)], (215, 220, 211))
    polygon(draw, [(0, 144), (46, 129), (88, 146), (139, 135), (176, 143), (222, 124), (275, 140), (320, 125), (320, 240), (0, 240)], (42, 84, 72))
    polygon(draw, [(0, 161), (75, 150), (135, 158), (198, 149), (261, 158), (320, 163), (320, 240), (0, 240)], (53, 136, 135))
    polygon(draw, [(100, 180), (160, 151), (205, 196), (256, 214), (320, 240), (20, 240)], (63, 125, 126))
    for i in range(12):
        y = 168 + i * 6
        line(draw, [(0, y), (58, y + 1), (151, y - 1), (252, y + 2), (320, y)], (131, 174, 153), 0.6)
    for i in range(16):
        x = i * 21
        tree(draw, x, 161 + 3 * math.sin(i), 24 + 5 * math.cos(i), (37, 78, 63))
    polygon(draw, [(0, 217), (48, 195), (79, 204), (115, 240), (0, 240)], (26, 61, 54))
    tree(draw, 12, 233, 104, (25, 57, 47))
    tree(draw, 302, 237, 127, (25, 57, 47))
    return image


def finish(image, seed):
    # Fixed-seed fine grain softens flat bands while keeping exports byte-stable.
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    rng = random.Random(seed)
    pixels = list(image.getdata())
    image.putdata([tuple(max(0, min(255, c + rng.randrange(-3, 4))) for c in rgb) for rgb in pixels])
    return image.quantize(colors=192, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)


def launcher_icon():
    # Own house geometry, authored at 32px: cream paper, ink roof and one amber
    # window connect the launcher tile to the next-event card inside Home HQ.
    k = 8
    image = Image.new("RGBA", (32 * k, 32 * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1 * k, 1 * k, 31 * k, 31 * k), radius=7 * k, fill=(242, 238, 230, 255))
    draw.polygon([(6 * k, 15 * k), (16 * k, 6 * k), (26 * k, 15 * k)], fill=(17, 17, 17, 255))
    draw.rounded_rectangle((9 * k, 13 * k, 23 * k, 26 * k), radius=k, fill=(17, 17, 17, 255))
    draw.rectangle((13 * k, 20 * k, 17 * k, 27 * k), fill=(242, 238, 230, 255))
    draw.rectangle((19 * k, 16 * k, 22 * k, 19 * k), fill=(255, 176, 0, 255))
    image = image.resize((32, 32), Image.Resampling.LANCZOS)
    return image.quantize(colors=64, method=Image.Quantize.FASTOCTREE)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for filename, render, seed in (("photo-coast.png", coast, 1), ("photo-lake.png", lake, 2), ("photo-mountain.png", mountain, 3)):
        out = ROOT / filename
        finish(render(), seed).save(out, optimize=False)
        print(out)
    icon = ROOT.parent / "icon.png"
    launcher_icon().save(icon, optimize=False)
    print(icon)


if __name__ == "__main__":
    main()
