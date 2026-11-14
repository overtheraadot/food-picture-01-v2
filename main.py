#!/usr/bin/env python3
"""Golden Ramen, Still Steaming -- make.fun food-picture-01 entry.

A 1024x1024 food picture drawn entirely by hand in pure Python 3
standard library: a small scanline rasterizer (ovals, polygons, Bezier
strokes) plus a hand-rolled PNG encoder on top of zlib. No files are
read, nothing touches the network, and every random choice comes from
one fixed seed, so two runs produce byte-identical PNGs.

The scene, from a high angle: a steaming bowl of ramen on a dark
wooden table. Golden broth with glossy chili-oil drops, a tangled nest
of wavy noodles, two halves of a soft-boiled egg with jammy yolks,
roast chashu, pink-swirled narutomaki, menma bamboo shoots, a sheet of
nori, spring onions and sesame -- chopsticks lifting a curl of noodles
through curling steam. Warm bright food on a dark table, no text: it
has to make you hungry at a glance and still read at 300 px.
"""

import math
import os
import struct
import zlib
from random import Random

W = H = 1024
SEED = 20261114

# Bowl geometry, high angle: wide shallow ovals.
BCX, BCY = 512, 578
BRX, BRY = 384, 306          # outer ceramic
IRX, IRY = 330, 258          # broth surface

# ---------------------------------------------------------------- palette
C = {
    "table":      (48, 31, 19),
    "table_dark": (26, 16, 10),
    "table_lite": (70, 48, 30),
    "glow":       (150, 96, 46),
    "ceramic":    (30, 32, 52),
    "ceramic_lt": (58, 62, 92),
    "ceramic_dk": (15, 16, 28),
    "rim":        (247, 238, 216),
    "broth":      (182, 110, 44),
    "broth_dark": (138, 76, 28),
    "broth_lite": (228, 156, 68),
    "broth_glow": (255, 198, 112),
    "noodle":     (246, 216, 150),
    "noodle_dk":  (212, 170, 102),
    "noodle_hi":  (255, 238, 192),
    "egg":        (251, 245, 230),
    "yolk":       (234, 128, 24),
    "yolk_dark":  (196, 94, 12),
    "yolk_hi":    (255, 178, 82),
    "naruto":     (246, 130, 152),
    "naruto_w":   (253, 247, 239),
    "onion":      (88, 170, 76),
    "onion_dark": (44, 110, 42),
    "onion_hi":   (152, 212, 122),
    "pork":       (198, 120, 88),
    "pork_dark":  (148, 80, 56),
    "pork_lite":  (230, 160, 122),
    "menma":      (206, 158, 74),
    "menma_dark": (164, 116, 44),
    "nori":       (20, 32, 20),
    "nori_lite":  (40, 60, 40),
    "stick":      (160, 106, 60),
    "stick_dark": (108, 66, 32),
    "stick_hi":   (200, 144, 86),
    "steam":      (242, 242, 236),
    "chili":      (208, 54, 36),
    "chili_oil":  (190, 60, 22),
    "sesame":     (251, 241, 215),
    "shadow":     (10, 7, 5),
}


# ---------------------------------------------------------------- raster
class Img:
    """Flat RGB buffer with scanline fill primitives."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 3)

    def span(self, y, x0, x1, rgb):
        """Opaque horizontal run."""
        if y < 0 or y >= self.h:
            return
        x0 = max(0, int(x0))
        x1 = min(self.w - 1, int(x1))
        if x1 < x0:
            return
        n = x1 - x0 + 1
        i = (y * self.w + x0) * 3
        self.buf[i:i + 3 * n] = bytes(rgb) * n

    def span_a(self, y, x0, x1, rgb, a):
        """Translucent horizontal run, a in [0, 1]."""
        if y < 0 or y >= self.h or a <= 0.0:
            return
        if a >= 1.0:
            self.span(y, x0, x1, rgb)
            return
        x0 = max(0, int(x0))
        x1 = min(self.w - 1, int(x1))
        if x1 < x0:
            return
        k = int(a * 256)
        m = 256 - k
        r, g, b = rgb
        i = (y * self.w + x0) * 3
        for _ in range(x1 - x0 + 1):
            self.buf[i] = (r * k + self.buf[i] * m) >> 8
            self.buf[i + 1] = (g * k + self.buf[i + 1] * m) >> 8
            self.buf[i + 2] = (b * k + self.buf[i + 2] * m) >> 8
            i += 3

    def pixel(self, x, y, rgb, a=1.0):
        if 0 <= x < self.w and 0 <= y < self.h and a > 0.0:
            k = int(a * 256)
            m = 256 - k
            i = (y * self.w + x) * 3
            self.buf[i] = (rgb[0] * k + self.buf[i] * m) >> 8
            self.buf[i + 1] = (rgb[1] * k + self.buf[i + 1] * m) >> 8
            self.buf[i + 2] = (rgb[2] * k + self.buf[i + 2] * m) >> 8

    def blob(self, cx, cy, r, rgb, a=1.0):
        """Filled disc."""
        r = int(r)
        for y in range(max(0, cy - r), min(self.h - 1, cy + r) + 1):
            dy = y - cy
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            self.span_a(y, cx - dx, cx + dx, rgb, a)

    def oval(self, cx, cy, rx, ry, rgb, a=1.0):
        rx, ry = int(rx), int(ry)
        for y in range(max(0, cy - ry), min(self.h - 1, cy + ry) + 1):
            t = (y - cy) / ry
            dx = int(rx * math.sqrt(max(0.0, 1.0 - t * t)))
            self.span_a(y, cx - dx, cx + dx, rgb, a)

    def oval_ring(self, cx, cy, rx, ry, thick, rgb, a=1.0):
        """Ring between an outer and a smaller inner oval."""
        rx, ry = int(rx), int(ry)
        ix, iy = max(1, rx - thick), max(1, ry - thick)
        for y in range(max(0, cy - ry), min(self.h - 1, cy + ry) + 1):
            t = (y - cy) / ry
            dx = int(rx * math.sqrt(max(0.0, 1.0 - t * t)))
            ti = (y - cy) / iy
            di = int(ix * math.sqrt(max(0.0, 1.0 - ti * ti))) if abs(ti) < 1 else -1
            if di >= 0:
                self.span_a(y, cx - dx, cx - di - 1, rgb, a)
                self.span_a(y, cx + di + 1, cx + dx, rgb, a)
            else:
                self.span_a(y, cx - dx, cx + dx, rgb, a)

    def rot_oval(self, cx, cy, rx, ry, ang, rgb, a=1.0):
        """Oval rotated by ang radians, rasterized as a polygon."""
        ca, sa = math.cos(ang), math.sin(ang)
        pts = []
        for k in range(36):
            th = 2 * math.pi * k / 36
            ex, ey = rx * math.cos(th), ry * math.sin(th)
            pts.append((int(cx + ex * ca - ey * sa),
                        int(cy + ex * sa + ey * ca)))
        self.fill_poly(pts, rgb, a)

    def fill_poly(self, pts, rgb, a=1.0):
        edges = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if y0 != y1:
                edges.append((y0, y1, x0, x1))
        lo = max(0, int(min(p[1] for p in pts)))
        hi = min(self.h - 1, int(max(p[1] for p in pts)))
        for y in range(lo, hi + 1):
            xs = []
            for y0, y1, x0, x1 in edges:
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.span_a(y, math.ceil(xs[i]), math.floor(xs[i + 1]), rgb, a)

    def stroke(self, pts, radius, rgb, a=1.0):
        """Polyline drawn as a chain of overlapping discs."""
        prev = None
        for x, y in pts:
            if prev is None:
                self.blob(x, y, radius, rgb, a)
            else:
                px, py = prev
                d = math.hypot(x - px, y - py)
                steps = max(1, int(d / 3))
                for i in range(1, steps + 1):
                    self.blob(int(px + (x - px) * i / steps),
                              int(py + (y - py) * i / steps),
                              radius, rgb, a)
            prev = (x, y)


def quad(p0, p1, p2, steps=24):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        out.append((int(u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]),
                    int(u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])))
    return out


def cubic(p0, p1, p2, p3, steps=24):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        out.append((int(u ** 3 * p0[0] + 3 * u * u * t * p1[0]
                        + 3 * u * t * t * p2[0] + t ** 3 * p3[0]),
                    int(u ** 3 * p0[1] + 3 * u * u * t * p1[1]
                        + 3 * u * t * t * p2[1] + t ** 3 * p3[1])))
    return out


def inside_broth(x, y):
    dx = (x - BCX) / IRX
    dy = (y - BCY) / IRY
    return dx * dx + dy * dy < 0.90


# ---------------------------------------------------------------- scene
def paint_backdrop(img, rng):
    # Dark wooden table, flat base colour first.
    for y in range(H):
        img.span(y, 0, W - 1, C["table"])
    # Plank seams: faint horizontal bands.
    for y0 in (140, 320, 690, 870):
        for k in range(5):
            img.span_a(y0 + k, 0, W - 1, C["table_dark"],
                       0.55 if k == 2 else 0.20)
    # Wood grain: long soft streaks, light and dark.
    for _ in range(52):
        y = rng.randrange(0, H)
        x = rng.randrange(0, 700)
        ln = rng.randrange(120, 430)
        img.span_a(y, x, x + ln,
                   rng.choice([C["table_lite"], C["table_dark"]]),
                   rng.uniform(0.08, 0.20))
    # Warm pool of light spilling across the table below the bowl.
    for y in range(200, H):
        t = 1.0 - (y - 200) / 824.0
        img.span_a(y, 70, 954, C["glow"], 0.05 * t)
    # Vignette: darken all four corners so the bowl pops.
    for cx, cy, rx, ry in [(0, 0, 560, 420), (W, 0, 560, 420),
                           (0, H, 580, 440), (W, H, 580, 440)]:
        img.oval(cx, cy, rx, ry, (8, 5, 3), 0.22)


def paint_bowl(img):
    # Soft contact shadow, then the deep indigo ceramic.
    img.oval(BCX, BCY + 28, BRX + 16, BRY + 12, C["shadow"], 0.45)
    img.oval(BCX, BCY, BRX, BRY, C["ceramic"])
    # Light catches the upper-left rim; shade pools lower-right.
    img.oval(BCX - 8, BCY - 10, BRX - 10, BRY - 10, C["ceramic_lt"], 0.35)
    img.oval(BCX + 12, BCY + 14, BRX - 18, BRY - 18, C["ceramic_dk"], 0.30)
    # Cream inner rim, then the broth surface.
    img.oval(BCX, BCY, BRX - 26, BRY - 22, C["rim"])
    img.oval(BCX, BCY, IRX, IRY, C["broth"])
    # Broth depth: darker toward the rim, golden heart in the middle.
    img.oval(BCX, BCY, IRX - 24, IRY - 20, C["broth_dark"], 0.35)
    img.oval(BCX - 18, BCY - 12, 252, 198, C["broth_lite"], 0.55)
    img.oval(BCX - 28, BCY - 22, 192, 148, C["broth_lite"], 0.35)
    # Glossy highlight where the light hits the broth.
    img.oval(BCX - 168, BCY - 148, 148, 50, C["broth_glow"], 0.30)
    img.oval(BCX - 148, BCY - 136, 88, 28, C["broth_glow"], 0.35)
    # Faint swirl rings on the broth surface, like stirred soup.
    for rx, ry, a in [(292, 226, 0.10), (238, 184, 0.12), (182, 140, 0.12)]:
        img.oval_ring(BCX - 10, BCY - 6, rx, ry, 7, C["broth_lite"], a)


def paint_chili_oil(img, rng):
    # Glossy red oil drops floating on the broth -- appetite colour.
    for _ in range(12):
        cx = rng.randrange(BCX - 240, BCX + 240)
        cy = rng.randrange(BCY - 170, BCY + 170)
        if not inside_broth(cx, cy):
            continue
        r = rng.choice([9, 11, 13, 16])
        img.blob(cx, cy, r, C["chili_oil"], 0.85)
        img.blob(cx, cy, max(2, r - 4), C["chili"], 0.8)
        img.blob(cx - r // 3, cy - r // 3, 2, (255, 150, 100), 0.9)


def strand(img, pts, radius, color, highlight=False):
    img.stroke(pts, radius, color, 0.95)
    if highlight:
        img.stroke(pts, max(1, radius - 3), C["noodle_hi"], 0.5)


def paint_noodles(img, rng):
    # A tangled nest of wavy strands across the broth: each strand is a
    # sine wave along a random direction, so the nest reads as curly
    # ramen rather than straight spaghetti.
    for _ in range(56):
        cx = rng.randrange(BCX - 250, BCX + 250)
        cy = rng.randrange(BCY - 180, BCY + 180)
        if not inside_broth(cx, cy):
            continue
        ang = rng.uniform(0, math.pi)
        ca, sa = math.cos(ang), math.sin(ang)
        ln = rng.uniform(80, 190)
        waves = rng.uniform(1.5, 3.0)
        amp = rng.uniform(8, 18)
        ph = rng.uniform(0, 6.28)
        pts = []
        for i in range(26):
            t = i / 25 - 0.5
            along = t * ln
            off = amp * math.sin(2 * math.pi * waves * t + ph)
            pts.append((int(cx + along * ca - off * sa),
                        int(cy + along * sa + off * ca)))
        if not inside_broth(*pts[0]) or not inside_broth(*pts[-1]):
            continue
        strand(img, pts, rng.choice([5, 6, 6, 7]),
               rng.choice([C["noodle"], C["noodle"], C["noodle_dk"]]),
               highlight=rng.random() < 0.45)
    # Tight little curls tucked between the long strands.
    for _ in range(9):
        cx = rng.randrange(BCX - 200, BCX + 200)
        cy = rng.randrange(BCY - 140, BCY + 140)
        if not inside_broth(cx, cy):
            continue
        r = rng.uniform(16, 30)
        pts = [(int(cx + r * 1.15 * math.cos(2 * math.pi * k / 24)),
                int(cy + r * 0.8 * math.sin(2 * math.pi * k / 24)))
               for k in range(24)]
        img.stroke(pts, 5, C["noodle"], 0.95)


def paint_pork(img):
    # Two overlapping slices of roasted chashu, left of the bowl.
    for cx, cy, rx, ry, rot in [(388, 472, 94, 68, 0.5),
                                (450, 544, 90, 64, -0.3)]:
        img.rot_oval(cx, cy, rx, ry, rot, C["pork_dark"])
        img.rot_oval(cx, cy, rx - 10, ry - 9, rot, C["pork"])
        img.rot_oval(cx, cy, rx - 34, ry - 30, rot, C["pork_lite"], 0.85)
        # Fatty edge glint.
        img.blob(cx - 30, cy - 26, 6, C["sesame"], 0.8)


def paint_menma(img, rng):
    # Golden bamboo shoots leaning on the right side of the bowl:
    # thick round-capped strokes with darker segment lines.
    for cx, cy, rot in [(792, 640, 0.9), (824, 600, 0.5), (760, 686, 1.2)]:
        sa, ca = math.sin(rot), math.cos(rot)
        p0 = (int(cx - 42 * sa), int(cy - 42 * ca))
        p1 = (int(cx + 42 * sa), int(cy + 42 * ca))
        img.stroke([p0, p1], 13, C["menma_dark"])
        img.stroke([p0, p1], 10, C["menma"])
        for f in (0.33, 0.66):
            mx, my = cx + (2 * f - 1) * 42 * sa, cy + (2 * f - 1) * 42 * ca
            img.stroke([(int(mx - 10 * ca), int(my + 10 * sa)),
                        (int(mx + 10 * ca), int(my - 10 * sa))],
                       2, C["menma_dark"], 0.6)
        img.blob(cx - 4, cy - 20, 3, C["broth_glow"], 0.7)


def paint_egg(img):
    # Two halves of a soft-boiled egg, upper right; jammy glossy yolks.
    for cx, cy, rot in [(696, 446, 0.45), (786, 524, -0.5)]:
        img.rot_oval(cx, cy, 68, 52, rot, (118, 68, 30), 0.5)
        img.rot_oval(cx, cy, 64, 49, rot, C["egg"])
        # Yolk: dark rim, deep orange body, bright jammy centre.
        img.oval(cx, cy, 38, 29, C["yolk_dark"])
        img.oval(cx - 2, cy - 2, 33, 25, C["yolk"])
        img.oval(cx - 6, cy - 6, 21, 15, C["yolk_hi"], 0.85)
        img.blob(cx - 13, cy - 11, 4, (255, 220, 160), 0.9)


def paint_naruto(img):
    # White fish cake with a pink spiral, lower left of the bowl.
    cx, cy = 368, 664
    img.blob(cx, cy, 47, C["naruto_w"])
    img.blob(cx, cy, 45, C["naruto"], 0.9)
    turns, steps = 2.6, 90
    pts = []
    for i in range(steps + 1):
        th = turns * 2 * math.pi * i / steps
        r = 4 + 37 * i / steps
        pts.append((int(cx + r * math.cos(th)), int(cy + r * math.sin(th))))
    img.stroke(pts, 6, C["naruto_w"], 0.95)
    img.blob(cx, cy, 5, C["naruto_w"])


def paint_nori(img):
    # A sheet of nori standing at the back-left edge of the broth.
    img.fill_poly([(328, 332), (392, 318), (406, 422), (344, 434)], C["nori"])
    img.fill_poly([(336, 336), (388, 326), (398, 410), (350, 420)],
                  C["nori_lite"], 0.7)


def paint_onions(img, rng):
    # Scattered spring-onion rings with a light catch on each.
    for _ in range(34):
        cx = rng.randrange(BCX - 280, BCX + 280)
        cy = rng.randrange(BCY - 200, BCY + 200)
        if not inside_broth(cx, cy):
            continue
        r = rng.choice([7, 8, 9])
        img.blob(cx, cy, r, C["onion"])
        img.blob(cx, cy, max(2, r - 4), C["onion_dark"])
        img.blob(cx - 2, cy - 2, 2, C["onion_hi"], 0.8)


def paint_garnish(img, rng):
    # Chili threads and sesame seeds over the broth.
    for _ in range(8):
        cx = rng.randrange(BCX - 180, BCX + 180)
        cy = rng.randrange(BCY - 130, BCY + 130)
        if not inside_broth(cx, cy):
            continue
        ang = rng.uniform(0, math.pi)
        ln = rng.randrange(22, 42)
        ca, sa = math.cos(ang), math.sin(ang)
        img.stroke([(int(cx - ln / 2 * ca), int(cy - ln / 2 * sa)),
                    (int(cx + ln / 2 * ca), int(cy + ln / 2 * sa))],
                   2, C["chili"], 0.95)
    for _ in range(28):
        cx = rng.randrange(BCX - 260, BCX + 260)
        cy = rng.randrange(BCY - 180, BCY + 180)
        if not inside_broth(cx, cy):
            continue
        img.blob(cx, cy, 2, C["sesame"], rng.uniform(0.6, 0.95))


def paint_chopsticks(img):
    # Chopsticks enter from the top right, tips pinching a lifted curl.
    tip = (668, 402)
    # Lifted noodle strands first, so the sticks lie on top of them.
    for k in range(5):
        off = (k - 2) * 9
        pts = cubic((640 + off, 472), (620 + off, 422),
                    (648 + off, 374), (tip[0] + off // 2, tip[1] + 6), 24)
        strand(img, pts, 6,
               C["noodle"] if k % 2 == 0 else C["noodle_dk"],
               highlight=(k % 2 == 0))
    # A small loop of noodles draped over the chopstick tips.
    loop = [(int(660 + 26 * math.cos(math.pi * i / 25)),
             int(398 + 18 * math.sin(math.pi * i / 25))) for i in range(26)]
    img.stroke(loop, 6, C["noodle"], 0.95)
    # The two tapered wooden sticks.
    for base, t in [((872, 128), (tip[0] - 8, tip[1] - 14)),
                    ((906, 176), (tip[0] + 10, tip[1] + 2))]:
        dx, dy = t[0] - base[0], t[1] - base[1]
        ln = math.hypot(dx, dy)
        nx, ny = -dy / ln, dx / ln
        w0, w1 = 11, 4
        img.fill_poly([
            (int(base[0] + nx * w0), int(base[1] + ny * w0)),
            (int(base[0] - nx * w0), int(base[1] - ny * w0)),
            (int(t[0] - nx * w1), int(t[1] - ny * w1)),
            (int(t[0] + nx * w1), int(t[1] + ny * w1)),
        ], C["stick"])
        img.stroke([(int(base[0] + nx * (w0 - 3)), int(base[1] + ny * (w0 - 3))),
                    (int(t[0] + nx * (w1 - 1)), int(t[1] + ny * (w1 - 1)))],
                   2, C["stick_hi"], 0.7)


def paint_steam(img, rng):
    # Curling steam rising above the bowl, soft and translucent.
    for cx, base_y, height, phase in [
        (398, 302, 212, 0.0),
        (500, 282, 252, 1.4),
        (600, 292, 232, 2.6),
        (690, 322, 182, 3.8),
        (328, 332, 162, 5.0),
    ]:
        pts = []
        for i in range(30):
            t = i / 29
            x = cx + int(26 * math.sin(phase + t * 5.2) * (0.4 + t))
            pts.append((x, int(base_y - t * height)))
        img.stroke(pts, 13, C["steam"], 0.10)
        img.stroke(pts, 6, C["steam"], 0.12)


# ---------------------------------------------------------------- PNG out
def encode_png(img):
    raw = bytearray()
    for y in range(img.h):
        raw.append(0)  # filter type: none
        raw += img.buf[y * img.w * 3:(y + 1) * img.w * 3]
    packed = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", packed)
    png += chunk(b"IEND", b"")
    return png


def main():
    rng = Random(SEED)
    img = Img(W, H)
    paint_backdrop(img, rng)
    paint_bowl(img)
    paint_chili_oil(img, rng)
    paint_noodles(img, rng)
    paint_pork(img)
    paint_menma(img, rng)
    paint_nori(img)
    paint_egg(img)
    paint_naruto(img)
    paint_onions(img, rng)
    paint_garnish(img, rng)
    paint_chopsticks(img)
    paint_steam(img, rng)

    # The grader sandbox runs with a read-only working directory and an
    # unset MAKEFUN_OUTPUT_DIR, so the default must be /output -- never
    # a path under the current directory.
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    data = encode_png(img)
    with open(path, "wb") as f:
        f.write(data)
    print(f"wrote {path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
