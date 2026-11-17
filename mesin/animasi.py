# -*- coding: utf-8 -*-
"""Engine animasi flat-explainer (gaya Kurzgesagt) — CPU only, tanpa GPU.

Aset digambar prosedural (PIL+numpy) sebagai layer terpisah, lalu di-composite + dianimasi dengan keyframe
(geser/skala/putar/transparansi) + efek prosedural (api, asap, glow, orbit, dadah). Tiap "adegan" = satu
template gerak (judul/roket/orbit/sorot/maskot) dengan durasi tertentu, lalu disambung jadi 1 video (9:16/16:9).

Dipakai mandiri buat uji:  python -m mesin.animasi
Nanti disambung ke pipeline sebagai visual-mode "animasi" (narasi + TTS + subtitle tetap dari mesin lama).
"""
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .alat import FFMPEG, OUTPUT, font as _font_path

SS = 2                       # supersample -> tepi halus
FPS = 30
UK = {"9:16": (1080, 1920), "16:9": (1920, 1080)}
FADE = 4                     # frame fade-in/out tiap adegan
MODEL_SUTRADARA = "qwen2.5:14b"   # model director+kritikus (qwen2.5 jago structured+instruksi); auto-pull kalau belum ada
MODEL_SUTRADARA_CADANGAN = "gemma4:12b-it-qat"   # kalau pull gagal / RAM kurang

# ---- palet flat ----
SPACE_TOP, SPACE_BOT = (26, 32, 70), (9, 12, 32)
EARTH_SEA, EARTH_LAND, EARTH_RIM = (58, 123, 213), (70, 192, 106), (120, 210, 255)
MOON, MOON_CRATER = (207, 211, 222), (176, 182, 198)
SUN, SUN_CORE, SUN_GLOW = (255, 205, 66), (255, 236, 150), (255, 170, 40)
MARS_SEA, MARS_LAND = (193, 86, 58), (150, 60, 40)
BODY, BODY_SHADE, ACCENT = (242, 244, 248), (208, 214, 226), (239, 83, 80)
WIN, WIN_RIM = (79, 195, 247), (33, 86, 120)
FLAME_OUT, FLAME_MID, FLAME_CORE = (255, 112, 67), (255, 202, 40), (255, 243, 192)
SMOKE = (215, 219, 230)
WATER, WATER_HI = (66, 165, 245), (187, 222, 251)
ATOM_NUC, ATOM_E, ATOM_ORBIT = (239, 83, 80), (79, 195, 247), (120, 140, 180)
MASKOT, MASKOT_BELLY, MASKOT_DARK = (38, 201, 214), (173, 236, 241), (20, 120, 130)
TEXT, ACCENT_Y = (255, 255, 255), (255, 202, 40)


# ======================================================================= util gambar
def P(x, y):
    return (x * SS, y * SS)


def _ell(d, cx, cy, r, fill):
    d.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], fill=fill)


def _layer(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _mask_lingkaran(size, cx, cy, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], fill=255)
    return m


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 3 * t * t - 2 * t * t * t


def overshoot(t, k=1.7):
    return 1 + (k + 1) * (t - 1) ** 3 + k * (t - 1) ** 2


# ---- gerak masuk bervariasi + hiasan (biar tiap adegan beda & nggak kosong) ----
def _entrance(var, prog, W, H):
    """var = ragam masuk (dirotasi per adegan); prog = i/(0.45s). Kembalikan (dx, dy, scale_masuk)."""
    e = ease_out(min(1, prog))
    v = int(var) % 5
    if v == 1:
        return (-0.75 * W) * (1 - e), 0.0, 0.6 + 0.4 * e      # geser dari kiri
    if v == 2:
        return (0.75 * W) * (1 - e), 0.0, 0.6 + 0.4 * e       # geser dari kanan
    if v == 3:
        return 0.0, (0.55 * H) * (1 - e), 0.7 + 0.3 * e       # naik dari bawah
    if v == 4:
        return 0.0, 0.0, 0.2 + 0.8 * e                        # membesar
    return 0.0, 0.0, overshoot(min(1, prog))                  # pop (overshoot)


_HIAS_WARNA = {"gurun": (235, 205, 150), "laut": (180, 222, 245), "langit": (255, 255, 255),
               "hijau": (195, 232, 175), "tubuh": (242, 185, 195), "angkasa": (255, 247, 214),
               "malam": (205, 214, 240), "sains": (150, 200, 240)}
# aset "tanda tangan" per tema buat visual besar di opening (hook)
_BG_ASET = {"gurun": "matahari", "laut": "tetes_air", "langit": "awan", "hijau": "pohon",
            "angkasa": "bumi", "malam": "bulan", "tubuh": "sel", "sains": "atom"}


def _hias(f, i, bg, W, H, seed=0):
    """Partikel kecil melayang (tema latar) supaya frame nggak kosong & terasa hidup."""
    d = ImageDraw.Draw(f)
    rng = np.random.default_rng((seed * 131 + hash(bg)) % 100000)
    col = _HIAS_WARNA.get(bg, (150, 200, 240))
    for _ in range(9):
        bx, by = rng.uniform(0.06, 0.94) * W, rng.uniform(0.08, 0.9) * H
        ph, sp, amp, rr = rng.uniform(0, 6.28), rng.uniform(0.6, 1.5), rng.uniform(8, 22), rng.uniform(3, 8)
        x = bx + amp * math.sin(i * 0.05 * sp + ph)
        y = by + amp * 0.6 * math.cos(i * 0.05 * sp + ph)
        a = int(70 + 55 * (0.5 + 0.5 * math.sin(i * 0.1 + ph)))
        _ell(d, x, y, rr, col + (a,))


# ---- furnitur bertema (elemen latar kecil biar adegan kerasa "dunia", bukan ikon doang) ----
def _kaktus(f, x, y, sc):
    d = ImageDraw.Draw(f)
    c = (66, 146, 88, 255)
    d.rounded_rectangle([P(x - 16 * sc, y - 120 * sc), P(x + 16 * sc, y)], radius=int(16 * sc * SS), fill=c)
    d.rounded_rectangle([P(x - 50 * sc, y - 100 * sc), P(x - 34 * sc, y - 52 * sc)], radius=int(10 * sc * SS), fill=c)
    d.rounded_rectangle([P(x - 50 * sc, y - 68 * sc), P(x - 18 * sc, y - 52 * sc)], radius=int(10 * sc * SS), fill=c)
    d.rounded_rectangle([P(x + 34 * sc, y - 110 * sc), P(x + 50 * sc, y - 60 * sc)], radius=int(10 * sc * SS), fill=c)
    d.rounded_rectangle([P(x + 18 * sc, y - 76 * sc), P(x + 50 * sc, y - 60 * sc)], radius=int(10 * sc * SS), fill=c)


def _burung(f, x, y, sc):
    d = ImageDraw.Draw(f)
    d.arc([P(x - 30 * sc, y - 16 * sc), P(x, y + 14 * sc)], 200, 340, fill=(44, 52, 72, 255), width=int(4 * SS))
    d.arc([P(x, y - 16 * sc), P(x + 30 * sc, y + 14 * sc)], 200, 340, fill=(44, 52, 72, 255), width=int(4 * SS))


def _ikan(f, x, y, sc):
    d = ImageDraw.Draw(f)
    c = (255, 150, 70, 255)
    _ell(d, x, y, 26 * sc, c)
    d.polygon([P(x + 20 * sc, y), P(x + 44 * sc, y - 16 * sc), P(x + 44 * sc, y + 16 * sc)], fill=c)
    _ell(d, x - 8 * sc, y - 4 * sc, 4 * sc, (20, 20, 20, 255))


def _pohon_kecil(f, x, y, sc=1.0):
    d = ImageDraw.Draw(f)
    d.rounded_rectangle([P(x - 10 * sc, y - 48 * sc), P(x + 10 * sc, y)], radius=int(5 * sc * SS), fill=(120, 85, 55, 255))
    _ell(d, x - 26 * sc, y - 52 * sc, 30 * sc, (78, 158, 92, 255))
    _ell(d, x + 26 * sc, y - 52 * sc, 30 * sc, (78, 158, 92, 255))
    _ell(d, x, y - 72 * sc, 40 * sc, (90, 170, 100, 255))


def _matahari_kecil(f, x, y, r):
    d = ImageDraw.Draw(f)
    for k in range(10):
        a = k / 10 * 6.283
        d.line([P(x + math.cos(a) * r * 1.25, y + math.sin(a) * r * 1.25),
                P(x + math.cos(a) * r * 1.55, y + math.sin(a) * r * 1.55)], fill=SUN + (255,), width=int(5 * SS))
    _ell(d, x, y, r, SUN + (255,))
    _ell(d, x - r * 0.25, y - r * 0.25, r * 0.5, SUN_CORE + (255,))


def _furnitur(f, i, bg, W, H, var=0):
    t = i / FPS
    sx = 0.82 if var % 2 == 0 else 0.18      # matahari gantian kiri/kanan tiap adegan
    jx = (var % 3) * 0.05                     # geser kecil biar nggak sama persis
    if bg == "gurun":
        _matahari_kecil(f, W * sx, H * 0.15, 58)
        _kaktus(f, W * (0.1 + jx), H * 0.82, 1.0)
        _kaktus(f, W * (0.9 - jx), H * 0.9, 0.7)
    elif bg == "langit":
        _matahari_kecil(f, W * sx, H * 0.14, 56)
        for k, bx in enumerate((0.22, 0.42, 0.3)):
            _burung(f, (bx + jx + 0.08 * math.sin(t * 0.4 + k)) * W, (0.3 + 0.05 * k) * H, 0.7 + 0.2 * k)
    elif bg == "laut":
        for k in range(3):
            _ikan(f, ((0.14 + 0.3 * k + jx) + 0.06 * math.sin(t * 0.8 + k)) * W, (0.72 + 0.06 * k) * H, 1 - 0.15 * k)
    elif bg == "hijau":
        _pohon_kecil(f, W * (0.1 + jx), H * 0.82, 1.1)
        _pohon_kecil(f, W * (0.9 - jx), H * 0.86, 0.9)


_FONTS = {}


def _huruf(px):
    k = int(px * SS)
    if k not in _FONTS:
        try:
            _FONTS[k] = ImageFont.truetype(_font_path("arialbd"), k)
        except Exception:
            _FONTS[k] = ImageFont.load_default()
    return _FONTS[k]


def teks(frame, s, cx, cy, px, fill=TEXT, anchor="mm", stroke=(10, 14, 30)):
    d = ImageDraw.Draw(frame)
    d.multiline_text(P(cx, cy), s, font=_huruf(px), fill=fill + (255,), anchor=anchor,
                     align="center", spacing=int(px * SS * 0.2),
                     stroke_width=max(2, int(px * SS * 0.07)), stroke_fill=stroke + (255,))


# ======================================================================= latar BERTEMA & bintang
# tiap tema: gradien (top->bot) + berbintang? + foreground statis opsional. Dipilih director per adegan ('bg').
_TEMA = {
    "angkasa": {"top": (26, 32, 70), "bot": (9, 12, 32), "bintang": True, "fg": None},
    "malam":   {"top": (22, 28, 58), "bot": (8, 10, 26), "bintang": True, "fg": "bulan_pojok"},
    "gurun":   {"top": (216, 138, 72), "bot": (120, 78, 52), "bintang": False, "fg": "dunes"},
    "langit":  {"top": (86, 148, 212), "bot": (150, 196, 234), "bintang": False, "fg": "awan"},
    "laut":    {"top": (60, 132, 186), "bot": (18, 68, 118), "bintang": False, "fg": "ombak"},
    "hijau":   {"top": (92, 156, 96), "bot": (48, 108, 62), "bintang": False, "fg": "bukit"},
    "sains":   {"top": (44, 74, 104), "bot": (20, 42, 68), "bintang": False, "fg": None},
    "tubuh":   {"top": (158, 74, 84), "bot": (92, 42, 58), "bintang": False, "fg": None},
}
_STARTEMA = {k for k, v in _TEMA.items() if v["bintang"]}
_BG = {}
_STAR = {}


def _grad(fmt, top, bot):
    W, H = UK[fmt]
    yv = np.linspace(0, 1, H * SS)
    col = np.array(top, float)[None, :] * (1 - yv)[:, None] + np.array(bot, float)[None, :] * yv[:, None]
    arr = np.repeat(col[:, None, :], W * SS, axis=1).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def _fg_dunes(f, fmt):
    W, H = UK[fmt]
    d = ImageDraw.Draw(f)
    for yy, c in ((0.80, (150, 100, 62)), (0.88, (176, 122, 74)), (0.96, (205, 150, 92))):
        d.ellipse([P(-W * 0.3, H * yy), P(W * 1.35, H * (yy + 0.55))], fill=c + (255,))


def _fg_awan(f, fmt):
    W, H = UK[fmt]
    d = ImageDraw.Draw(f)
    for cx, cy, r in ((0.22, 0.17, 0.095), (0.72, 0.11, 0.12), (0.5, 0.25, 0.075)):
        for dx in (-1, 0, 1):
            _ell(d, W * cx + dx * r * W * 0.75, H * cy, r * W, (255, 255, 255, 235))


def _fg_ombak(f, fmt):
    W, H = UK[fmt]
    d = ImageDraw.Draw(f)
    for k in range(4):
        yy = H * (0.62 + k * 0.095)
        d.line([P(x, yy + 10 * math.sin(x * 0.012 + k)) for x in range(0, W + 20, 20)],
               fill=(255, 255, 255, 55), width=int(5 * SS))


def _fg_bukit(f, fmt):
    W, H = UK[fmt]
    d = ImageDraw.Draw(f)
    for yy, c in ((0.80, (58, 118, 70)), (0.90, (80, 150, 86))):
        d.ellipse([P(-W * 0.3, H * yy), P(W * 1.35, H * (yy + 0.6))], fill=c + (255,))


def _fg_bulan_pojok(f, fmt):
    W, H = UK[fmt]
    bulan(f, W * 0.8, H * 0.15, 88)


_FG = {"dunes": _fg_dunes, "awan": _fg_awan, "ombak": _fg_ombak, "bukit": _fg_bukit, "bulan_pojok": _fg_bulan_pojok}


def latar(fmt, tema="angkasa"):
    key = (fmt, tema if tema in _TEMA else "angkasa")
    if key not in _BG:
        t = _TEMA[key[1]]
        f = _grad(fmt, t["top"], t["bot"])
        if t["fg"]:
            _FG[t["fg"]](f, fmt)
        _BG[key] = f
    return _BG[key].copy()


def _stars(fmt):
    if fmt not in _STAR:
        W, H = UK[fmt]
        rng = np.random.default_rng(7)
        _STAR[fmt] = [(rng.uniform(0, W), rng.uniform(0, H * 0.82), rng.uniform(1.6, 4.2),
                       rng.uniform(0, 6.28), rng.uniform(1.0, 3.0)) for _ in range(90)]
    return _STAR[fmt]


def bintang(frame, fmt, t):
    d = ImageDraw.Draw(frame)
    for x, y, r, ph, sp in _stars(fmt):
        b = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * sp + ph))
        v = int(150 + 105 * b)
        _ell(d, x, y, r * (0.8 + 0.4 * b), (v, v, int(v * 0.92), 255))


# ======================================================================= aset
def planet(frame, cx, cy, r, laut=EARTH_SEA, darat=EARTH_LAND, rim=EARTH_RIM, seed=1):
    glow = _layer(frame.size)
    _ell(ImageDraw.Draw(glow), cx, cy, r + 60, rim + (150,))
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(24 * SS)))
    ImageDraw.Draw(frame).ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], fill=laut + (255,))
    land = _layer(frame.size)
    ld = ImageDraw.Draw(land)
    rng = np.random.default_rng(seed)
    for _ in range(6):
        a, dist = rng.uniform(0, 6.28), rng.uniform(0, r * 0.55)
        lx, ly = cx + math.cos(a) * dist, cy + math.sin(a) * dist
        rx, ry = rng.uniform(r * 0.2, r * 0.42), rng.uniform(r * 0.14, r * 0.3)
        ld.ellipse([P(lx - rx, ly - ry), P(lx + rx, ly + ry)], fill=darat + (255,))
    la = ImageChops.multiply(land.split()[3], _mask_lingkaran(frame.size, cx, cy, r))
    land.putalpha(la)
    frame.alpha_composite(land)


def bulan(frame, cx, cy, r):
    d = ImageDraw.Draw(frame)
    _ell(d, cx, cy, r, MOON + (255,))
    for dx, dy, cr in [(-0.32, -0.2, 0.24), (0.27, 0.17, 0.19), (0.1, -0.38, 0.13), (-0.19, 0.38, 0.15)]:
        _ell(d, cx + dx * r, cy + dy * r, cr * r, MOON_CRATER + (255,))


def matahari(frame, cx, cy, r):
    glow = _layer(frame.size)
    _ell(ImageDraw.Draw(glow), cx, cy, r + 90, SUN_GLOW + (170,))
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30 * SS)))
    d = ImageDraw.Draw(frame)
    for k in range(12):
        a = k / 12 * 6.283
        x0, y0 = cx + math.cos(a) * r * 1.2, cy + math.sin(a) * r * 1.2
        x1, y1 = cx + math.cos(a) * r * 1.5, cy + math.sin(a) * r * 1.5
        d.line([P(x0, y0), P(x1, y1)], fill=SUN + (255,), width=int(7 * SS))
    _ell(d, cx, cy, r, SUN + (255,))
    _ell(d, cx - r * 0.28, cy - r * 0.28, r * 0.5, SUN_CORE + (255,))


def roket(frame, cx, cy, sc):
    d = ImageDraw.Draw(frame)
    bw, bh = 118 * sc, 316 * sc
    nh, finw = 112 * sc, 72 * sc
    top, bot = cy - bh / 2, cy + bh / 2
    d.polygon([P(cx - bw / 2, bot - 118 * sc), P(cx - bw / 2 - finw, bot + 14 * sc), P(cx - bw / 2, bot - 8 * sc)], fill=ACCENT)
    d.polygon([P(cx + bw / 2, bot - 118 * sc), P(cx + bw / 2 + finw, bot + 14 * sc), P(cx + bw / 2, bot - 8 * sc)], fill=ACCENT)
    d.rounded_rectangle([P(cx - bw / 2, top), P(cx + bw / 2, bot)], radius=bw / 2, fill=BODY)
    d.rounded_rectangle([P(cx + bw * 0.12, top), P(cx + bw / 2, bot)], radius=bw * 0.2, fill=BODY_SHADE)
    d.polygon([P(cx - bw * 0.34, bot - 6 * sc), P(cx + bw * 0.34, bot - 6 * sc),
               P(cx + bw * 0.24, bot + 30 * sc), P(cx - bw * 0.24, bot + 30 * sc)], fill=BODY_SHADE)
    d.polygon([P(cx, top - nh), P(cx - bw / 2, top + 10 * sc), P(cx + bw / 2, top + 10 * sc)], fill=ACCENT)
    wy = top + bh * 0.3
    _ell(d, cx, wy, 40 * sc, WIN_RIM + (255,))
    _ell(d, cx, wy, 33 * sc, WIN + (255,))
    _ell(d, cx - 11 * sc, wy - 11 * sc, 11 * sc, (255, 255, 255, 235))
    d.rounded_rectangle([P(cx - bw / 2, top + bh * 0.52), P(cx + bw / 2, top + bh * 0.58)], radius=6 * sc, fill=ACCENT)
    return cx, bot + 26 * sc, bw * 0.62


def api(frame, tx, ty, w, f):
    flick = 1 + 0.22 * math.sin(f * 0.9) + 0.12 * math.sin(f * 2.3 + 1) + 0.08 * math.sin(f * 5.1)
    L, jx = 150 * flick, 7 * math.sin(f * 1.7)
    glow = _layer(frame.size)
    ImageDraw.Draw(glow).polygon([P(tx - w, ty), P(tx + w, ty), P(tx + jx, ty + L * 1.15)], fill=FLAME_OUT + (170,))
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16 * SS)))
    d = ImageDraw.Draw(frame)
    for width, length, col in ((w, L, FLAME_OUT), (w * 0.62, L * 0.72, FLAME_MID), (w * 0.32, L * 0.46, FLAME_CORE)):
        d.polygon([P(tx - width, ty - 6), P(tx + width, ty - 6), P(tx + width * 0.5, ty + length * 0.5),
                   P(tx + jx, ty + length), P(tx - width * 0.5, ty + length * 0.5)], fill=col + (255,))


def tetes(frame, cx, cy, sc):
    d = ImageDraw.Draw(frame)
    w, h = 95 * sc, 150 * sc
    d.polygon([P(cx, cy - h * 0.7), P(cx + w * 0.5, cy), P(cx + w * 0.42, cy + h * 0.35),
               P(cx, cy + h * 0.5), P(cx - w * 0.42, cy + h * 0.35), P(cx - w * 0.5, cy)], fill=WATER + (255,))
    _ell(d, cx, cy + h * 0.1, w * 0.46, WATER + (255,))
    _ell(d, cx - w * 0.16, cy + h * 0.02, w * 0.16, WATER_HI + (230,))


def atom(frame, cx, cy, sc, t):
    d = ImageDraw.Draw(frame)
    R = 150 * sc
    for k in range(3):
        a = k * 60
        orb = _layer(frame.size)
        ImageDraw.Draw(orb).ellipse([P(cx - R, cy - R * 0.4), P(cx + R, cy + R * 0.4)],
                                    outline=ATOM_ORBIT + (255,), width=int(4 * SS))
        orb = orb.rotate(a, center=P(cx, cy), resample=Image.BILINEAR)
        frame.alpha_composite(orb)
    _ell(d, cx, cy, 44 * sc, ATOM_NUC + (255,))
    _ell(d, cx - 13 * sc, cy - 13 * sc, 14 * sc, (255, 170, 160, 220))
    for k in range(3):
        a = k * 60
        ang = t * 2.4 + k * 2.1
        ex, ey = R * math.cos(ang), R * 0.4 * math.sin(ang)
        rad = math.radians(a)
        rx = cx + ex * math.cos(rad) - ey * math.sin(rad)
        ry = cy + ex * math.sin(rad) + ey * math.cos(rad)
        _ell(d, rx, ry, 18 * sc, ATOM_E + (255,))


def maskot(frame, cx, cy, sc, wave=0.0, talk=0.0, point=None, glasses=False):
    """Maskot flat cyan. wave=dadah; talk=mulut buka (0..1, ngomong); point=(tx,ty) lengan kanan NUNJUK;
    glasses=pakai kacamata (mode presenter)."""
    d = ImageDraw.Draw(frame)
    rb = 110 * sc
    # lengan kiri (diam, turun)
    shl = (cx - rb * 0.75, cy - rb * 0.1)
    d.line([P(*shl), P(shl[0] - rb * 0.45, shl[1] + rb * 0.7)], fill=MASKOT + (255,), width=int(26 * sc))
    _ell(d, shl[0] - rb * 0.45, shl[1] + rb * 0.7, 17 * sc, MASKOT + (255,))
    # lengan kanan: nunjuk / dadah
    shr = (cx + rb * 0.75, cy - rb * 0.1)
    if point is not None:
        ang = math.atan2(point[1] - shr[1], point[0] - shr[0])
        hx, hy = shr[0] + math.cos(ang) * rb * 1.15, shr[1] + math.sin(ang) * rb * 1.15
    else:
        a = -0.5 - 0.9 * (0.5 + 0.5 * math.sin(wave))
        hx, hy = shr[0] + math.cos(a) * rb * 0.95, shr[1] - abs(math.sin(a)) * rb * 0.95
    d.line([P(*shr), P(hx, hy)], fill=MASKOT + (255,), width=int(26 * sc))
    _ell(d, hx, hy, 17 * sc, MASKOT + (255,))
    # badan + topi
    _ell(d, cx, cy, rb, MASKOT + (255,))
    _ell(d, cx, cy + rb * 0.2, rb * 0.62, MASKOT_BELLY + (255,))
    d.rounded_rectangle([P(cx - rb * 0.8, cy - rb * 1.02), P(cx + rb * 0.8, cy - rb * 0.86)], radius=8 * sc, fill=MASKOT_DARK)
    d.rounded_rectangle([P(cx - rb * 0.5, cy - rb * 1.35), P(cx + rb * 0.5, cy - rb * 0.9)], radius=14 * sc, fill=MASKOT_DARK)
    # mata
    for sx in (-0.34, 0.34):
        _ell(d, cx + sx * rb, cy - rb * 0.14, rb * 0.2, (255, 255, 255, 255))
        _ell(d, cx + sx * rb + rb * 0.05, cy - rb * 0.12, rb * 0.09, (20, 30, 45, 255))
    if glasses:
        for sx in (-0.34, 0.34):
            d.ellipse([P(cx + sx * rb - rb * 0.27, cy - rb * 0.14 - rb * 0.24), P(cx + sx * rb + rb * 0.27, cy - rb * 0.14 + rb * 0.24)],
                      outline=(28, 38, 54, 255), width=int(7 * sc))
        d.line([P(cx - rb * 0.07, cy - rb * 0.14), P(cx + rb * 0.07, cy - rb * 0.14)], fill=(28, 38, 54, 255), width=int(6 * sc))
    # mulut: ngomong (oval buka-tutup) atau senyum
    if talk > 0.05:
        mh = rb * (0.06 + 0.16 * talk)
        d.ellipse([P(cx - rb * 0.17, cy + rb * 0.2 - mh), P(cx + rb * 0.17, cy + rb * 0.2 + mh)], fill=(26, 56, 66, 255))
    else:
        d.arc([P(cx - rb * 0.32, cy + rb * 0.02), P(cx + rb * 0.32, cy + rb * 0.4)], 15, 165, fill=(20, 60, 70, 255), width=int(7 * sc))


def kartu_label(frame, s, cx, cy, px=58, warna=ACCENT_Y):
    f = _huruf(px)
    d = ImageDraw.Draw(frame)
    bbox = d.textbbox(P(cx, cy), s, font=f, anchor="mm")
    pad = int(26 * SS)
    d.rounded_rectangle([bbox[0] - pad, bbox[1] - pad // 2, bbox[2] + pad, bbox[3] + pad // 2],
                        radius=int(18 * SS), fill=warna + (255,))
    d.text(P(cx, cy), s, font=f, fill=(20, 24, 40, 255), anchor="mm")


def gelembung(frame, s, cx, cy, px=52):
    f = _huruf(px)
    d = ImageDraw.Draw(frame)
    bbox = d.textbbox(P(cx, cy), s, font=f, anchor="mm")
    pad = int(34 * SS)
    box = [bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad]
    d.rounded_rectangle(box, radius=int(30 * SS), fill=(255, 255, 255, 255))
    d.polygon([(box[0] + int(40 * SS), box[3] - 2), (box[0] + int(70 * SS), box[3] - 2),
               (box[0] + int(30 * SS), box[3] + int(40 * SS))], fill=(255, 255, 255, 255))
    d.text(P(cx, cy), s, font=f, fill=(30, 36, 52, 255), anchor="mm")


# ---- aset sains umum (flat, prosedural) — dipanggil lewat registry ASET ----
def termometer(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    tubw, tubh, br = 40 * sc, 240 * sc, 48 * sc
    top, bot = cy - tubh * 0.5, cy + tubh * 0.5
    d.rounded_rectangle([P(cx - tubw / 2, top), P(cx + tubw / 2, bot + br * 0.3)], radius=tubw / 2, fill=(245, 247, 250, 255))
    _ell(d, cx, bot + br * 0.3, br, (245, 247, 250, 255))
    frac = 0.55 + 0.12 * (0.5 + 0.5 * math.sin(t * 2))
    lvl = bot - tubh * 0.84 * frac
    d.rounded_rectangle([P(cx - tubw * 0.28, lvl), P(cx + tubw * 0.28, bot + br * 0.3)], radius=tubw * 0.28, fill=ACCENT)
    _ell(d, cx, bot + br * 0.3, br * 0.72, ACCENT)
    for k in range(4):
        yy = top + tubh * 0.15 + k * tubh * 0.22
        d.line([P(cx + tubw * 0.2, yy), P(cx + tubw * 0.5, yy)], fill=(120, 130, 150, 255), width=int(4 * sc))


def panas(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    for k in range(3):
        x = cx + (k - 1) * 48 * sc
        pts = [P(x + 15 * sc * math.sin(yy * 0.03 + t * 3 + k), cy + yy) for yy in range(int(-95 * sc), int(95 * sc), 8)]
        d.line(pts, fill=(255, 168, 60, 255), width=int(10 * sc), joint="curve")


def es(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    s = 120 * sc
    d.polygon([P(cx - s / 2, cy - s / 2), P(cx - s / 2 + 34 * sc, cy - s / 2 - 26 * sc),
               P(cx + s / 2 + 34 * sc, cy - s / 2 - 26 * sc), P(cx + s / 2, cy - s / 2)], fill=(206, 237, 250, 255))
    d.polygon([P(cx + s / 2, cy - s / 2), P(cx + s / 2 + 34 * sc, cy - s / 2 - 26 * sc),
               P(cx + s / 2 + 34 * sc, cy + s / 2 - 26 * sc), P(cx + s / 2, cy + s / 2)], fill=(150, 205, 235, 255))
    d.rounded_rectangle([P(cx - s / 2, cy - s / 2), P(cx + s / 2, cy + s / 2)], radius=16 * sc, fill=(185, 226, 246, 255))
    d.line([P(cx - s * 0.22, cy - s * 0.18), P(cx - s * 0.05, cy + s * 0.08)], fill=(255, 255, 255, 210), width=int(9 * sc))


def mata(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    w, h = 150 * sc, 92 * sc
    d.ellipse([P(cx - w, cy - h), P(cx + w, cy + h)], fill=(245, 248, 252, 255))
    _ell(d, cx, cy, h * 0.92, (79, 160, 220, 255))
    _ell(d, cx, cy, h * 0.5, (20, 30, 45, 255))
    _ell(d, cx - h * 0.3, cy - h * 0.32, h * 0.22, (255, 255, 255, 255))
    d.arc([P(cx - w, cy - h), P(cx + w, cy + h)], 182, 358, fill=(40, 50, 70, 255), width=int(8 * sc))


def sel(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    r = 145 * sc
    _ell(d, cx, cy, r, (176, 222, 158, 165))
    d.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], outline=(90, 170, 90, 255), width=int(9 * sc))
    _ell(d, cx, cy, r * 0.4, (124, 92, 182, 255))
    for ang, dd in [(0.5, 0.6), (2.1, 0.52), (3.7, 0.68), (5.0, 0.56)]:
        _ell(d, cx + math.cos(ang) * r * dd, cy + math.sin(ang) * r * dd, r * 0.12, (240, 170, 90, 255))


def dna(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    H = 200 * sc
    a, b = [], []
    for yy in range(int(-H), int(H), 6):
        ph = yy * 0.03 + t * 2
        a.append(P(cx + 42 * sc * math.sin(ph), cy + yy))
        b.append(P(cx + 42 * sc * math.sin(ph + math.pi), cy + yy))
    for i in range(0, len(a), 6):
        d.line([a[i], b[i]], fill=(255, 202, 40, 220), width=int(5 * sc))
    d.line(a, fill=(79, 195, 247, 255), width=int(11 * sc), joint="curve")
    d.line(b, fill=(239, 83, 80, 255), width=int(11 * sc), joint="curve")


def balon(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    r = 92 * sc
    _ell(d, cx, cy, r, (239, 83, 80, 255))
    _ell(d, cx - r * 0.3, cy - r * 0.35, r * 0.22, (255, 255, 255, 150))
    d.polygon([P(cx - 10 * sc, cy + r), P(cx + 10 * sc, cy + r), P(cx, cy + r + 18 * sc)], fill=(200, 60, 58, 255))
    d.line([P(cx + 14 * sc * math.sin(k * 0.5 + t), cy + r + 18 * sc + k * 7 * sc) for k in range(18)],
           fill=(180, 185, 195, 255), width=int(3 * sc))


def gelombang_suara(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    sx = cx - 120 * sc
    _ell(d, sx, cy, 30 * sc, (79, 195, 247, 255))
    for k in range(3):
        rr = (60 + k * 58) * sc
        d.arc([P(sx - rr, cy - rr), P(sx + rr, cy + rr)], -52, 52, fill=(120, 200, 245, 255), width=int(9 * sc))


def termos(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    w, h = 92 * sc, 240 * sc
    d.rounded_rectangle([P(cx - w / 2, cy - h / 2 + 32 * sc), P(cx + w / 2, cy + h / 2)], radius=24 * sc, fill=(90, 150, 200, 255))
    d.rounded_rectangle([P(cx - w * 0.38, cy - h / 2), P(cx + w * 0.38, cy - h / 2 + 42 * sc)], radius=14 * sc, fill=(60, 110, 160, 255))
    d.rounded_rectangle([P(cx - w / 2, cy - h * 0.08), P(cx + w / 2, cy + h * 0.06)], radius=6 * sc, fill=(240, 245, 250, 255))
    d.line([P(cx - w * 0.22, cy - h * 0.28), P(cx - w * 0.22, cy + h * 0.3)], fill=(255, 255, 255, 120), width=int(9 * sc))


def hewan(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    bw, bh, col = 170 * sc, 92 * sc, (150, 120, 90, 255)
    d.rounded_rectangle([P(cx - bw / 2, cy - bh / 2), P(cx + bw / 2, cy + bh / 2)], radius=42 * sc, fill=col)
    _ell(d, cx + bw * 0.5, cy - bh * 0.3, 46 * sc, col)
    d.polygon([P(cx + bw * 0.46, cy - bh * 0.3 - 44 * sc), P(cx + bw * 0.4, cy - bh * 0.3 - 6 * sc),
               P(cx + bw * 0.58, cy - bh * 0.3 - 10 * sc)], fill=col)
    for lx in (-0.3, -0.08, 0.2, 0.42):
        d.rounded_rectangle([P(cx + bw * lx - 11 * sc, cy + bh * 0.25), P(cx + bw * lx + 11 * sc, cy + bh * 0.5 + 52 * sc)], radius=9 * sc, fill=col)
    _ell(d, cx + bw * 0.6, cy - bh * 0.36, 7 * sc, (20, 20, 20, 255))


def lampu(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    r = 72 * sc
    glow = _layer(f.size)
    _ell(ImageDraw.Draw(glow), cx, cy, r + 40 * sc, (255, 220, 120, 120))
    f.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14 * SS)))
    _ell(d, cx, cy, r, (255, 224, 130, 255))
    d.rounded_rectangle([P(cx - r * 0.5, cy + r * 0.7), P(cx + r * 0.5, cy + r * 1.25)], radius=8 * sc, fill=(165, 165, 175, 255))
    d.line([P(cx - r * 0.25, cy + r * 0.2), P(cx - r * 0.1, cy - r * 0.2), P(cx + r * 0.1, cy + r * 0.2), P(cx + r * 0.25, cy - r * 0.2)],
           fill=(230, 150, 40, 255), width=int(5 * sc), joint="curve")
    for k in range(6):
        a = k / 6 * 6.283
        d.line([P(cx + math.cos(a) * (r + 20 * sc), cy + math.sin(a) * (r + 20 * sc)),
                P(cx + math.cos(a) * (r + 46 * sc), cy + math.sin(a) * (r + 46 * sc))], fill=(255, 202, 40, 255), width=int(6 * sc))


def magnet(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    w, bar = 150 * sc, 46 * sc
    grey = (150, 150, 160, 255)
    d.arc([P(cx - w / 2, cy - w / 2), P(cx + w / 2, cy + w / 2)], 180, 360, fill=grey, width=int(bar))
    for sgn, col in ((-1, ACCENT + (255,)), (1, (79, 130, 230, 255))):
        x = cx + sgn * (w / 2 - bar / 2)
        d.line([P(x, cy), P(x, cy + w * 0.5)], fill=grey, width=int(bar))
        d.line([P(x, cy + w * 0.4), P(x, cy + w * 0.5)], fill=col, width=int(bar))


def bintang_besar(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = (72 if k % 2 == 0 else 31) * sc
        pts.append(P(cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon(pts, fill=(255, 202, 40, 255))


def gunung(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    base = cy + 130 * sc
    for dx, w, h, c in ((-95 * sc, 160 * sc, 205 * sc, (120, 104, 132, 255)),
                        (80 * sc, 140 * sc, 235 * sc, (102, 88, 114, 255)),
                        (0 * sc, 182 * sc, 295 * sc, (136, 118, 146, 255))):
        px, top = cx + dx, base - (h if dx == 0 else (h))
        top = base - h
        d.polygon([P(px, top), P(px - w, base), P(px + w, base)], fill=c)
        d.polygon([P(px, top), P(px - w * 0.3, top + h * 0.26), P(px + w * 0.3, top + h * 0.26)], fill=(240, 245, 250, 255))


def awan(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    w = 150 * sc
    for dx, dy, r in ((-0.55, 0.1, 0.42), (0.55, 0.1, 0.42), (-0.2, -0.2, 0.5), (0.25, -0.15, 0.48), (0, 0.15, 0.56)):
        _ell(d, cx + dx * w, cy + dy * w, r * w, (246, 249, 252, 255))
    for k in range(4):
        rx = cx + (k - 1.5) * 46 * sc + 8 * sc * math.sin(t * 3 + k)
        d.line([P(rx, cy + 0.5 * w), P(rx - 6 * sc, cy + 0.5 * w + 42 * sc)], fill=(96, 164, 224, 255), width=int(7 * sc))


def pohon_aset(f, cx, cy, sc, t=0):
    d = ImageDraw.Draw(f)
    d.rounded_rectangle([P(cx - 22 * sc, cy), P(cx + 22 * sc, cy + 120 * sc)], radius=int(14 * sc * SS), fill=(122, 86, 56, 255))
    _ell(d, cx - 70 * sc, cy - 20 * sc, 62 * sc, (86, 166, 100, 255))
    _ell(d, cx + 70 * sc, cy - 20 * sc, 62 * sc, (86, 166, 100, 255))
    _ell(d, cx, cy - 64 * sc, 95 * sc, (78, 158, 92, 255))
    _ell(d, cx, cy - 10 * sc, 76 * sc, (98, 178, 112, 255))


# registry: nama aset (dipakai director LLM) -> fungsi gambar (f, cx, cy, sc, t)
ASET = {
    "bumi": lambda f, cx, cy, sc, t: planet(f, cx, cy, 150 * sc),
    "planet": lambda f, cx, cy, sc, t: planet(f, cx, cy, 150 * sc),
    "mars": lambda f, cx, cy, sc, t: planet(f, cx, cy, 150 * sc, MARS_SEA, MARS_LAND, (255, 150, 110), seed=9),
    "bulan": lambda f, cx, cy, sc, t: bulan(f, cx, cy, 110 * sc),
    "matahari": lambda f, cx, cy, sc, t: matahari(f, cx, cy, 120 * sc),
    "roket": lambda f, cx, cy, sc, t: roket(f, cx, cy, sc),
    "atom": atom,
    "tetes_air": lambda f, cx, cy, sc, t: tetes(f, cx, cy, sc),
    "bintang": bintang_besar,
    "termometer": termometer, "panas": panas, "es": es, "mata": mata, "sel": sel, "dna": dna,
    "balon": balon, "gelombang_suara": gelombang_suara, "termos": termos, "hewan": hewan,
    "lampu": lampu, "magnet": magnet, "gunung": gunung, "awan": awan, "pohon": pohon_aset,
}


# ======================================================================= adegan (template gerak)
class Adegan:
    def __init__(self, n, p, fmt):
        self.n, self.p, self.fmt = n, p or {}, fmt
        self.W, self.H = UK[fmt]
        self.bg = (p or {}).get("bg") if (p or {}).get("bg") in _TEMA else "angkasa"
        self._statis = None

    def statis(self):
        if self._statis is None:
            self._statis = self.bangun_statis()
        return self._statis.copy()

    def bangun_statis(self):
        return latar(self.fmt, self.bg)

    def taburi_bintang(self, f, t):
        if self.bg in _STARTEMA:
            bintang(f, self.fmt, t)

    def frame(self, i):
        f = self.statis()
        self.gambar(f, i)
        return f

    def gambar(self, f, i):
        pass


class Judul(Adegan):
    def gambar(self, f, i):
        self.taburi_bintang(f, i / FPS)
        _furnitur(f, i, self.bg, self.W, self.H, self.p.get("var", 0))
        _hias(f, i, self.bg, self.W, self.H, seed=5)
        t = i / FPS
        # HOOK: visual besar "tanda tangan" topik (pop-in gede) biar retensi awal kuat
        aset = self.p.get("aset") if self.p.get("aset") in ASET else _BG_ASET.get(self.bg)
        vp = ease_out(min(1, i / (0.4 * FPS)))
        if aset in ASET and vp > 0:
            ASET[aset](f, self.W / 2, self.H * 0.52, (0.2 + 1.25 * vp) * (1 + 0.05 * math.sin(t * 1.8)), t)
        sc = overshoot(min(1, (i + 1) / (0.42 * FPS)))
        s = _judul_pendek(self.p.get("judul", "SAINS"))
        px = _fit_px(f, s, self.W * 0.9, 88)
        teks(f, s, self.W / 2, self.H * 0.2, px * sc)
        wlen = ease_out(min(1, max(0, (i - 0.25 * FPS) / (0.4 * FPS))))
        if wlen > 0:
            w = self.W * 0.32 * wlen
            ImageDraw.Draw(f).rounded_rectangle(
                [P(self.W / 2 - w, self.H * 0.285), P(self.W / 2 + w, self.H * 0.296)], radius=6 * SS, fill=ACCENT_Y + (255,))
        naik = ease_out(min(1, max(0, (i - 0.3 * FPS) / (0.4 * FPS))))   # maskot host muncul
        if naik > 0:
            maskot(f, self.W / 2, self.H * 0.82 + (0.3 * self.H) * (1 - naik) + 9 * math.sin(t * 2), 0.9, wave=i * 0.5)


class Roket(Adegan):
    def bangun_statis(self):
        self.bg = "angkasa"
        f = latar(self.fmt, "angkasa")
        bulan(f, self.W * 0.77, self.H * 0.19, 105)
        planet(f, self.W / 2, self.H * 1.07, self.W * 0.83, seed=3)
        return f

    def gambar(self, f, i):
        if getattr(self, "_i", None) != i - 1:
            self._smoke = []
        self._i = i
        self.taburi_bintang(f, i / FPS)
        tt = i / max(1, self.n - 1)
        p = 0.0 if tt < 0.12 else ((tt - 0.12) / 0.88) ** 1.7
        cy = self.H * 0.78 + (self.H * 0.16 - self.H * 0.78) * p
        cx = self.W / 2 + 9 * math.sin(tt * 22)
        sc = 1 - 0.17 * p
        tx, ty, fw = cx, cy + (316 * sc) / 2 + 26 * sc, 118 * sc * 0.62
        rng = np.random.default_rng(i)
        if 0.04 < tt < 0.62:
            for _ in range(3):
                self._smoke.append([tx + rng.uniform(-18, 18), ty + rng.uniform(0, 30),
                                    rng.uniform(-3.2, 3.2), rng.uniform(1.6, 4), 0, rng.integers(26, 46), rng.uniform(26, 46)])
        sl = _layer(f.size)
        sd = ImageDraw.Draw(sl)
        alive = []
        for s in self._smoke:
            s[0] += s[2]; s[1] += s[3]; s[4] += 1; s[6] += 1.6
            if s[4] < s[5]:
                _ell(sd, s[0], s[1], s[6], SMOKE + (int(150 * (1 - s[4] / s[5])),))
                alive.append(s)
        self._smoke = alive
        f.alpha_composite(sl.filter(ImageFilter.GaussianBlur(7 * SS)))
        api(f, tx, ty, fw, i)
        roket(f, cx, cy, sc)
        if self.p.get("label"):
            kartu_label(f, self.p["label"], self.W / 2, self.H * 0.9)


class Orbit(Adegan):
    PUSAT = {"bumi": lambda f, cx, cy, r: planet(f, cx, cy, r),
             "matahari": lambda f, cx, cy, r: matahari(f, cx, cy, r * 0.9)}
    KELILING = {"bulan": lambda f, cx, cy: bulan(f, cx, cy, 52),
                "bumi": lambda f, cx, cy: planet(f, cx, cy, 60, seed=5)}

    def bangun_statis(self):
        self.bg = "angkasa"
        f = latar(self.fmt, "angkasa")
        cx, cy = self.W / 2, self.H / 2
        R = self.W * 0.34
        ImageDraw.Draw(f).ellipse([P(cx - R, cy - R * 0.42), P(cx + R, cy + R * 0.42)],
                                  outline=(90, 110, 150, 180), width=int(3 * SS))
        self.PUSAT.get(self.p.get("pusat", "bumi"), self.PUSAT["bumi"])(f, cx, cy, 150)
        return f

    def gambar(self, f, i):
        self.taburi_bintang(f, i / FPS)
        cx, cy = self.W / 2, self.H / 2
        R = self.W * 0.34
        ang = i / self.n * 6.283 * 1.3 - 1.57
        ox, oy = cx + R * math.cos(ang), cy + R * 0.42 * math.sin(ang)
        self.KELILING.get(self.p.get("keliling", "bulan"), self.KELILING["bulan"])(f, ox, oy)
        if self.p.get("label"):
            kartu_label(f, self.p["label"], self.W / 2, self.H * 0.88)


class Sorot(Adegan):
    """Komposisi: aset UTAMA + 1-3 elemen pendukung (objek relevan dari kalimat), masuk bergiliran + gerak.
    Biar tiap layar RAME & NYAMBUNG (bukan 1 objek di bg kosong)."""
    _POS = [(0.2, 0.33), (0.8, 0.35), (0.5, 0.7), (0.18, 0.66)]

    def gambar(self, f, i):
        self.taburi_bintang(f, i / FPS)
        _furnitur(f, i, self.bg, self.W, self.H, self.p.get("var", 0))
        _hias(f, i, self.bg, self.W, self.H, seed=abs(hash(self.p.get("aset", ""))) % 1000)
        t, prog = i / FPS, i / (0.45 * FPS)
        settle = min(1, prog)
        main = self.p.get("aset", "lampu")
        elemen = [e for e in (self.p.get("elemen") or []) if e in ASET and e != main][:4]
        # elemen pendukung: masuk bergiliran (stagger) + ngambang beda-beda fase
        for k, e in enumerate(elemen):
            ep = ease_out(min(1, max(0, (i - (0.3 + k * 0.16) * FPS) / (0.4 * FPS))))
            if ep <= 0:
                continue
            ex, ey = self._POS[k]
            ASET[e](f, self.W * ex + 12 * math.sin(t * 1.3 + k), self.H * ey + 16 * math.sin(t * 1.9 + k * 1.3),
                    ep * 0.5 * (1 + 0.06 * math.sin(t * 2 + k)), t)
        # aset utama (lebih kecil kalau ada elemen, biar muat) + entrance + idle
        dx, dy, esc = _entrance(self.p.get("var", 0), prog, self.W, self.H)
        cx, cy = self.W / 2 + dx, self.H * 0.45 + dy + 10 * math.sin(t * 2.2) * settle
        sc = esc * (1.0 if elemen else 1.28) * (1 + 0.03 * math.sin(t * 1.7) * settle)
        ASET.get(main, ASET["lampu"])(f, cx, cy, sc, t)
        if self.p.get("label"):
            lp = ease_out(min(1, max(0, (i - 0.2 * FPS) / (0.3 * FPS))))
            if lp > 0:
                kartu_label(f, self.p["label"], self.W / 2, self.H * 0.88 + 36 * (1 - lp))


class Banding(Adegan):
    """Dua aset masuk dari sisi berlawanan + 'VS' yang nge-pop + partikel hias."""
    def gambar(self, f, i):
        self.taburi_bintang(f, i / FPS)
        _furnitur(f, i, self.bg, self.W, self.H, self.p.get("var", 0))
        _hias(f, i, self.bg, self.W, self.H, seed=321)
        t = i / FPS
        e = ease_out(min(1, i / (0.45 * FPS)))
        for key, lab, fx, arah in (("kiri", "label_kiri", 0.28, -1), ("kanan", "label_kanan", 0.72, 1)):
            cx = self.W * fx + arah * (0.5 * self.W) * (1 - e)
            cy = self.H * 0.42 + 8 * math.sin(t * 2 + (0 if arah < 0 else 1.5))
            ASET.get(self.p.get(key, "lampu"), ASET["lampu"])(f, cx, cy, 0.78 * (0.6 + 0.4 * e), t)
            if self.p.get(lab) and e > 0.5:
                kartu_label(f, self.p[lab], self.W * fx, self.H * 0.66, px=44)
        teks(f, "VS", self.W / 2, self.H * 0.42, 74 * overshoot(min(1, i / (0.5 * FPS))), fill=ACCENT_Y)


class Maskot(Adegan):
    def gambar(self, f, i):
        self.taburi_bintang(f, i / FPS)
        _furnitur(f, i, self.bg, self.W, self.H, self.p.get("var", 0))
        _hias(f, i, self.bg, self.W, self.H, seed=77)
        t = i / FPS
        naik = ease_out(min(1, i / (0.4 * FPS)))
        cy = self.H * 0.6 + 10 * math.sin(t * 2) + (0.3 * self.H) * (1 - naik)
        maskot(f, self.W / 2, cy, 1.0, wave=i * 0.5)
        if self.p.get("teks") and naik > 0.6:
            gelembung(f, self.p["teks"], self.W / 2, self.H * 0.3)


def _lerp3(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def _gambar_di_kotak(f, draw_fn, box, radius=14):
    """Gambar draw_fn(layer) lalu clip ke kotak (box=[x0,y0,x1,y1] koordinat final)."""
    layer = _layer(f.size)
    draw_fn(layer)
    mask = Image.new("L", f.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([P(box[0], box[1]), P(box[2], box[3])], radius=int(radius * SS), fill=255)
    layer.putalpha(ImageChops.multiply(layer.split()[3], mask))
    f.alpha_composite(layer)


def _termo_frac(f, cx, cy, frac, sc=0.8):
    """Termometer level=frac (0..1); warna isi biru(dingin)->merah(panas) ikut frac."""
    d = ImageDraw.Draw(f)
    tubw, tubh, br = 40 * sc, 240 * sc, 48 * sc
    top, bot = cy - tubh * 0.5, cy + tubh * 0.5
    d.rounded_rectangle([P(cx - tubw / 2, top), P(cx + tubw / 2, bot + br * 0.3)], radius=int(tubw / 2 * SS), fill=(245, 247, 250, 255))
    _ell(d, cx, bot + br * 0.3, br, (245, 247, 250, 255))
    col = _lerp3((90, 150, 210), (239, 83, 80), frac)
    lvl = bot - tubh * 0.84 * max(0.08, min(1, frac))
    d.rounded_rectangle([P(cx - tubw * 0.28, lvl), P(cx + tubw * 0.28, bot + br * 0.3)], radius=int(tubw * 0.28 * SS), fill=col + (255,))
    _ell(d, cx, bot + br * 0.3, br * 0.72, col)


class Presenter(Adegan):
    """Resep PRESENTER: maskot guru (kacamata) nunjuk LAYAR proyektor berisi gambar tema, mulut ngomong."""
    def bangun_statis(self):
        f = _grad(self.fmt, (74, 100, 136), (44, 62, 92))
        ImageDraw.Draw(f).rectangle([P(0, self.H * 0.72), P(self.W, self.H)], fill=(126, 100, 76, 255))
        return f

    def gambar(self, f, i):
        t, W, H = i / FPS, self.W, self.H
        e = ease_out(min(1, i / (0.45 * FPS)))
        box = [W * 0.14, H * 0.09 - (1 - e) * H * 0.1, W * 0.86, H * 0.44 - (1 - e) * H * 0.1]
        ImageDraw.Draw(f).rounded_rectangle([P(box[0] - 16, box[1] - 16), P(box[2] + 16, box[3] + 16)],
                                            radius=int(22 * SS), fill=(24, 30, 44, 255))
        tc = _TEMA.get(self.p.get("bg", "gurun"), _TEMA["sains"])

        def isi(layer):
            ld = ImageDraw.Draw(layer)
            ld.rectangle([P(box[0], box[1]), P(box[2], box[3])], fill=tc["top"] + (255,))
            ld.rectangle([P(box[0], (box[1] + box[3]) * 0.52), P(box[2], box[3])], fill=tc["bot"] + (255,))
            aset = self.p.get("aset")
            if aset in ASET:
                ASET[aset](layer, (box[0] + box[2]) / 2, (box[1] + box[3]) * 0.52, 0.6, t)
        _gambar_di_kotak(f, isi, box, radius=12)
        mcx, mcy = W * 0.3, H * 0.82 + (1 - e) * H * 0.2
        maskot(f, mcx, mcy, 1.0, point=((box[0] + box[2]) / 2, box[3]), glasses=True, talk=0.5 + 0.5 * math.sin(t * 10))
        if self.p.get("label"):
            kartu_label(f, self.p["label"], W * 0.72, H * 0.84)


class SiangMalam(Adegan):
    """Resep SIANG->MALAM->BEKU: matahari turun, bulan naik, langit gelap, suhu turun merah->biru, tanah membeku."""
    def bangun_statis(self):
        return latar(self.fmt, "angkasa")   # tak dipakai; frame() override penuh

    def frame(self, i):
        p, W, H = i / max(1, self.n - 1), self.W, self.H
        f = _grad(self.fmt, _lerp3((120, 170, 225), (18, 22, 50), p), _lerp3((250, 200, 140), (10, 14, 32), p))
        d = ImageDraw.Draw(f)
        if p > 0.45:
            for x, y, r, ph, sp in _stars(self.fmt):
                if y < H * 0.6:
                    _ell(d, x, y, r, (240, 240, 255, int(200 * min(1, (p - 0.45) * 2.2))))
        _matahari_kecil(f, W * 0.28, H * (0.2 + 0.82 * p), 72)
        bulan(f, W * 0.72, H * (1.15 - 0.95 * p), 70)
        ground = H * 0.78
        d.rectangle([P(0, ground), P(W, H)], fill=_lerp3((206, 120, 70), (96, 150, 212), p) + (255,))
        if p > 0.7:
            for k in range(7):
                _ell(d, W * (0.08 + 0.13 * k), ground + 28, 11 * min(1, (p - 0.7) * 3.3), (232, 246, 255, 220))
        _termo_frac(f, W * 0.87, H * 0.42, 1 - p)
        kartu_label(f, self.p.get("label") or ("MEMBEKU" if p > 0.6 else "MATAHARI TERBENAM"), W * 0.42, H * 0.9, px=44)
        return f


def _awan_bentuk(f, cx, cy, w, col=(246, 249, 252)):
    d = ImageDraw.Draw(f)
    for dx, dy, r in ((-0.55, 0.1, 0.42), (0.55, 0.1, 0.42), (-0.2, -0.22, 0.5), (0.25, -0.16, 0.48), (0, 0.15, 0.56)):
        _ell(d, cx + dx * w, cy + dy * w, r * w, col + (255,))


def _hujan(f, i, x0, x1, ytop, ybot, seed=0, warna=(120, 180, 235)):
    d = ImageDraw.Draw(f)
    rng = np.random.default_rng(seed)
    for _ in range(26):
        x = rng.uniform(x0, x1)
        ph, spd = rng.uniform(0, 1), rng.uniform(0.85, 1.4)
        yy = ytop + ((i * spd * 0.055 + ph) % 1.0) * (ybot - ytop)
        d.line([P(x, yy), P(x - 5, yy + 34)], fill=warna + (220,), width=int(4 * SS))


def _gunung_satu(f, cx, base, w, h, col):
    d = ImageDraw.Draw(f)
    top = base - h
    d.polygon([P(cx, top), P(cx - w, base), P(cx + w, base)], fill=col + (255,))
    d.polygon([P(cx, top), P(cx - w * 0.3, top + h * 0.26), P(cx + w * 0.3, top + h * 0.26)], fill=(240, 245, 250, 255))


class Hujan(Adegan):
    """Resep HUJAN: awan beneran + hujan turun (bukan tetes diam) + genangan."""
    def bangun_statis(self):
        return latar(self.fmt, self.bg if self.bg in ("langit", "malam") else "langit")

    def gambar(self, f, i):
        t, W, H = i / FPS, self.W, self.H
        e = ease_out(min(1, i / (0.45 * FPS)))
        for cx, cy, w in ((W * 0.32, H * 0.26, W * 0.15), (W * 0.62, H * 0.22, W * 0.17), (W * 0.48, H * 0.32, W * 0.13)):
            _awan_bentuk(f, cx, cy - (1 - e) * H * 0.1, w * (0.6 + 0.4 * e), (235, 240, 246))
        _hujan(f, i, W * 0.18, W * 0.82, H * 0.38, H * 0.82)
        d = ImageDraw.Draw(f)
        for k in range(5):      # genangan bawah
            _ell(d, W * (0.15 + 0.17 * k), H * 0.88, (18 + 6 * math.sin(t * 3 + k)), (110, 170, 225, 200))
        if self.p.get("label"):
            kartu_label(f, self.p["label"], W / 2, H * 0.92)


class BayanganHujan(Adegan):
    """Resep BAYANGAN HUJAN: 2 gunung apit gurun; awan keblok gunung kiri → hujan di sisi kiri, GURUN kering di tengah."""
    def bangun_statis(self):
        W, H = self.W, self.H
        f = _grad(self.fmt, (120, 170, 225), (236, 198, 140))
        d = ImageDraw.Draw(f)
        base = H * 0.72
        d.rectangle([P(0, base), P(W, H)], fill=(220, 176, 116, 255))
        _ell(d, W * 0.5, base + H * 0.14, W * 0.34, (202, 156, 100, 255))
        _gunung_satu(f, W * 0.2, base, W * 0.28, H * 0.44, (104, 90, 116))
        _gunung_satu(f, W * 0.82, base, W * 0.24, H * 0.36, (118, 104, 130))
        return f

    def gambar(self, f, i):
        t, W, H = i / FPS, self.W, self.H
        e = ease_out(min(1, i / (0.55 * FPS)))
        cxc = W * (-0.05 + 0.28 * e)                      # awan masuk dari kiri ke gunung
        _awan_bentuk(f, cxc, H * 0.2, W * 0.15, (210, 216, 224))
        _hujan(f, i, W * 0.08, W * 0.3, H * 0.26, H * 0.66)   # hujan di sisi gunung (windward)
        _matahari_kecil(f, W * 0.55, H * 0.15, 54)           # gurun kering terik di tengah
        _kaktus(f, W * 0.52, H * 0.84, 0.9)
        kartu_label(f, self.p.get("label") or "BAYANGAN HUJAN", W * 0.5, H * 0.93, px=40)


TEMPLATE = {"judul": Judul, "roket": Roket, "orbit": Orbit, "sorot": Sorot, "banding": Banding,
            "maskot": Maskot, "presenter": Presenter, "siang_malam": SiangMalam,
            "hujan": Hujan, "bayangan_hujan": BayanganHujan}


# ======================================================================= render
# ======================================================================= sutradara (narasi -> adegan)
_ASET_LABEL = {"termometer": "SUHU", "panas": "PANAS", "es": "DINGIN", "gelombang_suara": "SUARA",
               "tetes_air": "AIR", "balon": "GAS", "sel": "SEL", "dna": "DNA", "mata": "MATA",
               "magnet": "MAGNET", "matahari": "MATAHARI", "bumi": "BUMI", "bulan": "BULAN", "mars": "MARS",
               "atom": "ATOM", "roket": "ROKET", "hewan": "HEWAN", "lampu": "IDE", "bintang": "BINTANG",
               "termos": "TERMOS", "planet": "PLANET", "gunung": "GUNUNG", "awan": "AWAN", "pohon": "POHON"}

# aturan keyword (fallback kalau LLM mati / tak kebaca). Urut: cocok pertama menang.
_KW = [
    (r"matahari terbenam|senja|panas.{0,20}siang.{0,30}dingin.{0,20}malam|dingin.{0,20}malam.{0,30}panas.{0,20}siang|"
     r"suhu.{0,20}(turun|anjlok).{0,20}malam|membeku.{0,20}malam|malam.{0,20}membeku", {"tipe": "siang_malam", "label": "MALAM"}),
    (r"bayangan hujan|rain shadow|diapit.{0,15}gunung|gunung.{0,25}(halang|blok|hadang|tahan).{0,15}awan|"
     r"awan.{0,15}(terhalang|keblok|tertahan).{0,15}gunung|dikelilingi pegunungan|pegunungan mengurung", {"tipe": "bayangan_hujan", "label": "BAYANGAN HUJAN"}),
    (r"turun hujan|hujan turun|air hujan|hujan deras|mendung|awan.{0,15}hujan", {"tipe": "hujan", "label": "HUJAN"}),
    (r"roket|meluncur|luncur|dorong|propuls|wahana antariksa", {"tipe": "roket", "label": "DORONGAN"}),
    (r"orbit|mengelilingi|mengitari|revolusi|ngitar", {"tipe": "orbit", "pusat": "bumi", "keliling": "bulan", "label": "ORBIT"}),
    (r"\bbulan\b", {"tipe": "sorot", "aset": "bulan"}),
    (r"matahari|surya", {"tipe": "sorot", "aset": "matahari"}),
    (r"\bmars\b", {"tipe": "sorot", "aset": "mars"}),
    (r"\b(bumi|planet|dunia)\b", {"tipe": "sorot", "aset": "bumi"}),
    (r"atom|elektron|proton|neutron|partikel|molekul", {"tipe": "sorot", "aset": "atom"}),
    (r"suhu|derajat|temperatur|termometer", {"tipe": "sorot", "aset": "termometer"}),
    (r"panas|kalor|membara|terik|hangat", {"tipe": "sorot", "aset": "panas"}),
    (r"\bes\b|beku|membeku|salju|dingin", {"tipe": "sorot", "aset": "es"}),
    (r"mata|lihat|penglihat|retina|pupil|gelap", {"tipe": "sorot", "aset": "mata"}),
    (r"\bsel\b|penuaan|jaringan|organ|tubuh", {"tipe": "sorot", "aset": "sel"}),
    (r"\bdna\b|\bgen\b|genetik|kromosom", {"tipe": "sorot", "aset": "dna"}),
    (r"balon|helium|\bgas\b", {"tipe": "sorot", "aset": "balon"}),
    (r"suara|bunyi|dengar|frekuensi|getar|akustik", {"tipe": "sorot", "aset": "gelombang_suara"}),
    (r"termos|botol|termal|insulasi", {"tipe": "sorot", "aset": "termos"}),
    (r"gunung|pegunungan|puncak|tebing|lembah|bukit", {"tipe": "sorot", "aset": "gunung"}),
    (r"awan|mendung|hujan|kabut|badai", {"tipe": "sorot", "aset": "awan"}),
    (r"pohon|hutan|tumbuhan|daun|tanaman|rimba", {"tipe": "sorot", "aset": "pohon"}),
    (r"unta|zebra|hewan|binatang|kucing|anjing|singa|burung|ikan|ubur", {"tipe": "sorot", "aset": "hewan"}),
    (r"air|cair|tetes|basah|lembap|lembab|\buap\b|hujan", {"tipe": "sorot", "aset": "tetes_air"}),
    (r"magnet|kutub|tarik-menarik|medan", {"tipe": "sorot", "aset": "magnet"}),
    (r"\bbintang\b", {"tipe": "sorot", "aset": "bintang"}),
    (r"lampu|listrik|cahaya|energi|\bide\b|arus", {"tipe": "sorot", "aset": "lampu"}),
]


_KW_BG = [
    (r"gurun|pasir|sahara|atacama|tandus", "gurun"),
    (r"laut|samudra|lautan|ombak|pantai|bawah air|ikan|terumbu|pesisir", "laut"),
    (r"hutan|pohon|daun|tumbuhan|savana|rumput|tanaman", "hijau"),
    (r"langit|awan|hujan|atmosfer|terbang|burung|badai", "langit"),
    (r"malam|gelap|nokturnal|tidur|senja", "malam"),
    (r"planet|antariksa|ruang angkasa|orbit|galaksi|roket|\bbulan\b|matahari|venus|mars|bintang|komet|meteor", "angkasa"),
    (r"\bsel\b|tubuh|organ|darah|jantung|otak|\bdna\b|penuaan|bakteri|virus|saraf|paru", "tubuh"),
]


def _keyword_bg(teks, default="sains"):
    t = (teks or "").lower()
    for pat, bg in _KW_BG:
        if re.search(pat, t):
            return bg
    return default


def _keyword_spec(teks):
    t = (teks or "").lower()
    for pat, spec in _KW:
        if re.search(pat, t):
            s = dict(spec)
            if s["tipe"] == "sorot":
                s.setdefault("label", _ASET_LABEL.get(s["aset"], s["aset"].upper()))
            return s
    if t.strip().endswith("?"):
        return {"tipe": "maskot", "teks": "Kenapa ya?"}
    return {"tipe": "sorot", "aset": "lampu", "label": "FAKTA"}


def _judul_pendek(t, per_baris=15):
    """Bungkus judul ke baris pendek (±15 char) biar muat di frame; buang kata sambung sisa kalau kepanjangan."""
    t = re.sub(r"[^\w\s?!]", "", t or "").strip().upper()
    baris, cur = [], ""
    for w in t.split():
        if cur and len(cur) + 1 + len(w) > per_baris:
            baris.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        baris.append(cur)
    return "\n".join(baris[:4]) or "SAINS"


def _fit_px(frame, s, maks_lebar, base_px):
    """Kecilin font kalau baris terpanjang lebih lebar dari maks_lebar (koordinat final px)."""
    d = ImageDraw.Draw(frame)
    panjang = max((d.textlength(b, font=_huruf(base_px)) for b in s.split("\n")), default=0)
    batas = maks_lebar * SS
    return base_px if panjang <= batas or panjang == 0 else max(30, base_px * batas / panjang)


def _bersihkan_spec(a, teks, bg_default="sains"):
    """Validasi 1 spec dari LLM; jatuh ke keyword kalau tak valid. Sisipkan 'bg' (tema latar)."""
    bg = a.get("bg") if a.get("bg") in _TEMA else bg_default
    tipe = a.get("tipe")
    lab = (a.get("label") or "").strip().upper()[:16]
    if tipe == "foto":   # footage/foto ASLI dari web (ditangani di pipeline, bukan template animasi)
        return {"tipe": "foto", "query": ((a.get("query") or "").strip() or teks[:60])[:80], "label": lab, "bg": bg}
    if tipe not in TEMPLATE:
        s = _keyword_spec(teks)
        s["bg"] = bg
        return s
    if tipe == "sorot":
        aset = a.get("aset") if a.get("aset") in ASET else (_keyword_spec(teks).get("aset") or "lampu")
        # label jangan sekadar nama aset (mis. "TETES_AIR"/"HEWAN") → pakai label bersih
        if not lab or lab.lower().replace(" ", "_") == aset.lower():
            lab = _ASET_LABEL.get(aset, aset.upper())
        elemen = [e for e in (a.get("elemen") or []) if e in ASET and e != aset][:4]
        return {"tipe": "sorot", "aset": aset, "elemen": elemen, "label": lab, "bg": bg}
    if tipe == "banding":
        ki = a.get("kiri") if a.get("kiri") in ASET else None
        ka = a.get("kanan") if a.get("kanan") in ASET else None
        if not ki or not ka or ki == ka:   # banding tak valid → jatuh ke sorot
            aset = ki or ka or (_keyword_spec(teks).get("aset") or "lampu")
            return {"tipe": "sorot", "aset": aset, "label": lab or _ASET_LABEL.get(aset, aset.upper()), "bg": bg}
        return {"tipe": "banding", "kiri": ki, "kanan": ka, "bg": bg,
                "label_kiri": _ASET_LABEL.get(ki, ki.upper()), "label_kanan": _ASET_LABEL.get(ka, ka.upper())}
    if tipe == "orbit":
        return {"tipe": "orbit", "pusat": "bumi", "keliling": "bulan", "label": lab or "ORBIT", "bg": "angkasa"}
    if tipe == "maskot":
        return {"tipe": "maskot", "teks": (a.get("label") or "Hmm…")[:24], "bg": bg}
    if tipe == "presenter":
        aset = a.get("aset") if a.get("aset") in ASET else (_keyword_spec(teks).get("aset") or "lampu")
        return {"tipe": "presenter", "aset": aset, "label": lab, "bg": bg}
    if tipe == "siang_malam":
        return {"tipe": "siang_malam", "label": lab or "MALAM", "bg": bg}
    if tipe in ("hujan", "bayangan_hujan"):
        return {"tipe": tipe, "label": lab or ("HUJAN" if tipe == "hujan" else "BAYANGAN HUJAN"), "bg": bg}
    return {"tipe": "judul", "judul": _judul_pendek(lab or teks), "bg": bg}


def _pastikan_model(cfg, model, log=print):
    """True kalau model ada di ollama; kalau belum, PULL dulu (sekali) — biar git-clone + jalan otomatis siap."""
    try:
        from . import ollama
        if model in (ollama.daftar_model(cfg) or []):
            return True
        import requests
        log(f"  ⬇️ model {model} belum ada di mini PC — pull dulu (sekali, bisa belasan menit)…")
        r = requests.post(cfg["ollama_url"].rstrip("/") + "/api/pull", json={"name": model}, stream=True, timeout=3600)
        for _ in r.iter_lines():
            pass
        return model in (ollama.daftar_model(cfg) or [])
    except Exception as e:
        log(f"  pull {model} gagal: {str(e)[:70]}")
        return False


def kritik(cfg, judul, baris, spec, batal=None, log=print):
    """Pass REVIEW (multi-agent): LLM ngoreksi pilihan sutradara — buang repetisi, benerin resep/aset salah,
    label spesifik. Kembalikan spec yang diperbaiki (fallback ke spec asli kalau gagal)."""
    n = len(baris)
    try:
        from . import ollama
        keys = list(ASET.keys())

        def _ket(s):
            x = s.get("aset") or s.get("query") or (f"{s.get('kiri')}+{s.get('kanan')}" if s.get("kiri") else "")
            return f"[{s.get('tipe')}{'/' + x if x else ''}] '{s.get('label') or s.get('teks') or s.get('judul', '')}'"
        ringkas = "\n".join(f"{i + 1}. {_ket(s)} — {baris[i][:58]}" for i, s in enumerate(spec))
        sis = ("Kamu EDITOR video sains animasi flat. Di bawah ini pilihan adegan dari sutradara. PERBAIKI:\n"
               "1) JANGAN ada tipe/aset yang diulang berturut-turut — variasikan.\n"
               "2) Tiap adegan WAJIB cocok makna kalimatnya — ganti tipe/aset kalau salah.\n"
               "3) 'label' = kata PALING SPESIFIK & benar dari kalimat (BUKAN nama aset).\n"
               "4) Maskot cukup di pembuka/penutup. Pakai resep (siang_malam/hujan/bayangan_hujan/presenter) kalau pas.\n"
               "Aset: " + ", ".join(keys) + ". Tipe: " + ", ".join(list(TEMPLATE) + ["foto"]) + ".\n"
               "Keluarkan ULANG SEMUA adegan (jumlah & urutan SAMA) yang sudah diperbaiki.")
        schema = {"type": "object", "properties": {"adegan": {"type": "array", "items": {"type": "object",
                  "properties": {"tipe": {"type": "string", "enum": list(TEMPLATE) + ["foto"]},
                                 "aset": {"type": "string", "enum": keys}, "kiri": {"type": "string", "enum": keys},
                                 "kanan": {"type": "string", "enum": keys}, "query": {"type": "string"},
                                 "label": {"type": "string"}}, "required": ["tipe", "label"]}}}, "required": ["adegan"]}
        j = ollama.chat_json(cfg, [{"role": "system", "content": sis},
                                   {"role": "user", "content": f"Judul: {judul}\nPilihan sutradara:\n{ringkas}"}],
                             schema, batal=batal, maks_token=55 * n + 220, suhu=0.3)
        arr = (j or {}).get("adegan") or []
        if len(arr) >= n * 0.7:
            out = [spec[0]]   # adegan 0 tetap judul
            for i in range(1, n):
                a = arr[i] if i < len(arr) else {}
                s = _bersihkan_spec(a, baris[i], spec[i].get("bg", "sains"))
                s["var"] = spec[i].get("var", i)
                out.append(s)
            log(f"  🔍 Kritikus review {n} adegan selesai")
            return out
    except Exception as e:
        log(f"  Kritikus gagal ({str(e)[:60]}) — pakai pilihan sutradara")
    return spec


_PAKSA = [   # resep DIPAKSA kalau narasi jelas cocok (LLM sering milih banding/sorot yang 'aman')
    (r"matahari terbenam|panas.{0,20}siang.{0,30}(dingin|beku|anjlok).{0,20}malam|membeku.{0,20}malam|"
     r"malam.{0,20}membeku|suhu.{0,15}(anjlok|turun drastis)", "siang_malam"),
    (r"gunung.{0,25}(halang|blok|hadang|tahan).{0,18}awan|diapit.{0,15}gunung|bayangan hujan|"
     r"awan.{0,18}(terhalang|keblok|tertahan).{0,15}gunung|hujan.{0,15}sisi.{0,15}gunung|pegunungan.{0,20}menghalangi", "bayangan_hujan"),
    (r"turun hujan|hujan turun|hujan deras|hujan lebat", "hujan"),
]
_PAKSA_LABEL = {"siang_malam": "MALAM", "bayangan_hujan": "BAYANGAN HUJAN", "hujan": "HUJAN"}


def _paksa_resep(baris, spec):
    """Paksa resep proses kalau narasi jelas cocok (biar resep spesifik pasti kepakai, bukan tergantung mood LLM)."""
    for i in range(1, len(spec)):
        t = (baris[i] or "").lower()
        for pat, resep in _PAKSA:
            if re.search(pat, t) and spec[i].get("tipe") != resep:
                spec[i] = {"tipe": resep, "label": spec[i].get("label") or _PAKSA_LABEL[resep],
                           "bg": spec[i].get("bg", "sains"), "var": spec[i].get("var", i)}
                break
    return spec


def _rapikan(baris, spec):
    """Pembersihan deterministik (pengganti LLM-kritikus yang ngacak): label bersih + maskot cuma penutup + dedup."""
    keyset = {k.lower() for k in ASET}
    n = len(spec)
    # 1) label 'sorot' bersih (bukan gabungan nama aset / '+' / kepanjangan)
    for s in spec:
        if s.get("tipe") == "sorot":
            lab, aset = (s.get("label") or "").strip(), s.get("aset", "lampu")
            if (not lab) or ("+" in lab) or (lab.lower() in keyset) or (lab.lower().replace(" ", "_") in keyset) or len(lab) > 16:
                s["label"] = _ASET_LABEL.get(aset, aset.upper())
    # 2) maskot cuma di adegan TERAKHIR (penutup); maskot di tengah → jadi sorot
    for i in range(1, n - 1):
        if spec[i].get("tipe") == "maskot":
            s = _keyword_spec(baris[i])
            s["bg"], s["var"] = spec[i].get("bg", "sains"), spec[i].get("var", i)
            spec[i] = s
    if n and spec[-1].get("tipe") == "maskot":    # CTA penutup yang bener (bukan "MASKOT")
        tk = (spec[-1].get("teks") or "").strip()
        if (not tk) or tk.lower() in keyset or tk.lower() in ("maskot", "") or len(tk) > 22:
            spec[-1]["teks"] = "Subscribe ya!"
    # 3) dedup: 2 adegan beruntun yang sama → variasikan yang ke-2
    for i in range(1, n):
        a, b = spec[i - 1], spec[i]
        if a.get("tipe") == b.get("tipe") == "sorot" and a.get("aset") == b.get("aset"):
            alt = _keyword_spec(baris[i]).get("aset")
            if alt and alt != b.get("aset"):
                b["aset"], b["label"] = alt, _ASET_LABEL.get(alt, alt.upper())
        elif a.get("tipe") == b.get("tipe") == "banding":   # banding beruntun → ke-2 jadi sorot
            ki = b.get("kiri") if b.get("kiri") in ASET else "lampu"
            spec[i] = {"tipe": "sorot", "aset": ki, "label": _ASET_LABEL.get(ki, ki.upper()),
                       "bg": b.get("bg", "sains"), "var": b.get("var", i)}
    return spec


def sutradara(cfg, judul, baris, batal=None, log=print):
    """baris = daftar kalimat narasi. Kembalikan 1 spec adegan per kalimat (template+aset+label).
    Pakai gemma (structured JSON); fallback aturan keyword per baris. Baris pertama selalu 'judul'."""
    n = len(baris)
    spec = [None] * n
    bg_utama = _keyword_bg(f"{judul} {' '.join(baris)}")   # tema latar default dari topik
    tema_keys = list(_TEMA.keys())
    llm_ok = False
    try:
        from . import ollama
        cfg = dict(cfg)
        if _pastikan_model(cfg, MODEL_SUTRADARA, log):
            cfg["model"] = MODEL_SUTRADARA
        elif MODEL_SUTRADARA_CADANGAN in (ollama.daftar_model(cfg) or []):
            cfg["model"] = MODEL_SUTRADARA_CADANGAN
        keys = list(ASET.keys())
        sis = ("Kamu pengarah video SAINS animasi flat (gaya Kurzgesagt) untuk penonton muda Indonesia. "
               "Untuk TIAP kalimat narasi, pilih SATU adegan visual yang paling mewakili maknanya.\n"
               "Template: 'judul'=kalimat pembuka; 'roket'=peluncuran/ke luar angkasa; 'orbit'=mengelilingi/revolusi; "
               "'banding'=membandingkan DUA hal; 'maskot'=sapaan/ajakan (CUKUP di pembuka/penutup); "
               "'sorot'=tampilkan SATU benda (DEFAULT); 'foto'=FOTO/VIDEO ASLI dari web buat TEMPAT/BENDA NYATA "
               "spesifik (mis. gurun Atacama, aurora, unta).\n"
               "RESEP KHUSUS (lebih bagus dari 'sorot', pakai kalau COCOK): 'presenter'=karakter GURU (kacamata) "
               "jelasin di depan PROYEKTOR (buat kalimat PENJELASAN/pembuka — isi 'aset' buat gambar di layar); "
               "'siang_malam'=sekuens matahari TERBENAM → bulan naik → suhu TURUN → tanah MEMBEKU (khusus kalimat soal "
               "panas di siang & dingin/beku di malam); 'hujan'=awan + HUJAN TURUN (kalimat soal hujan/mendung); "
               "'bayangan_hujan'=2 gunung apit gurun, awan keblok gunung → hujan di 1 sisi, gurun kering (kalimat soal "
               "gunung menghalangi awan/hujan atau gurun diapit pegunungan).\n"
               "Untuk 'sorot' pilih 'aset' UTAMA + 'elemen' = 1-3 aset PENDUKUNG lain yang relevan/disebut di kalimat "
               "(biar adegan RAME & NYAMBUNG, bukan 1 objek; mis. 'matahari memanggang pasir panas' → aset:matahari, "
               "elemen:[panas,termometer]). 'banding' WAJIB 'kiri'+'kanan' DUA aset BEDA; 'foto' WAJIB 'query' "
               "Inggris spesifik. Aset dari daftar ini saja: " + ", ".join(keys) + ".\n"
               "VARIASI: jangan ngulang 'banding'/'maskot' berturut-turut; mayoritas 'sorot' dengan aset BEDA-BEDA; "
               "pakai 'foto' hemat (1-3x/video, buat establishing shot). Kalau NGGAK ADA aset yang pas buat subjek, "
               "pakai 'foto' (query real) — JANGAN maksa aset yang salah makna (mis. jangan 'bumi' buat gunung).\n"
               "'label' = 1-2 kata HURUF BESAR, kata PALING SPESIFIK dari kalimat (mis. 'UNTA', 'HELIUM', 'VENUS'). "
               "JANGAN pakai nama aset sebagai label (jangan 'HEWAN'/'TETES_AIR').\n"
               "'bg_utama' = tema latar UTAMA video (konsisten) dari: " + ", ".join(tema_keys) + " "
               "(angkasa=ruang/planet, gurun=pasir, langit=awan/udara, laut=air/laut, hijau=alam/hutan, "
               "malam, sains=netral/fisika/kimia, tubuh=biologi/organ). Tiap adegan boleh kasih 'bg' sendiri "
               "kalau beda jauh, kalau nggak kosongkan (ikut bg_utama).\n"
               "Keluarkan TEPAT satu adegan per kalimat, urut sama.")
        isi = f"Judul: {judul}\n\nKalimat narasi:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(baris))
        schema = {"type": "object", "properties": {
                  "bg_utama": {"type": "string", "enum": tema_keys},
                  "adegan": {"type": "array", "items": {"type": "object",
                  "properties": {"tipe": {"type": "string", "enum": list(TEMPLATE) + ["foto"]},
                                 "aset": {"type": "string", "enum": keys},
                                 "elemen": {"type": "array", "items": {"type": "string", "enum": keys}},
                                 "kiri": {"type": "string", "enum": keys},
                                 "kanan": {"type": "string", "enum": keys},
                                 "query": {"type": "string"},
                                 "bg": {"type": "string", "enum": tema_keys},
                                 "label": {"type": "string"}}, "required": ["tipe", "label"]}}},
                  "required": ["bg_utama", "adegan"]}
        j = ollama.chat_json(cfg, [{"role": "system", "content": sis}, {"role": "user", "content": isi}],
                             schema, batal=batal, maks_token=55 * n + 220, suhu=0.4)
        if (j or {}).get("bg_utama") in _TEMA:
            bg_utama = j["bg_utama"]
        arr = (j or {}).get("adegan") or []
        for i in range(min(n, len(arr))):
            spec[i] = _bersihkan_spec(arr[i], baris[i], bg_utama)
        llm_ok = sum(1 for s in spec if s) >= n * 0.6
        log(f"  🎬 Sutradara AI: {sum(1 for s in spec if s)}/{n} adegan (tema latar: {bg_utama})")
    except Exception as e:
        log(f"  Sutradara AI gagal ({str(e)[:70]}) — pakai aturan keyword (tema {bg_utama})")
    for i in range(n):
        if not spec[i]:
            s = _keyword_spec(baris[i])
            s["bg"] = "angkasa" if s["tipe"] in ("roket", "orbit") else bg_utama
            spec[i] = s
    spec[0] = {"tipe": "judul", "judul": _judul_pendek(judul or baris[0]), "bg": bg_utama}
    for k, s in enumerate(spec):     # ragam gerak masuk dirotasi biar adegan berurutan nggak monoton
        s.setdefault("var", k)
    spec = _paksa_resep(baris, spec)  # jamin resep proses kepakai kalau narasi jelas cocok
    spec = _rapikan(baris, spec)      # bersihin label jelek + dedup repetisi (deterministik, anti-ngacak)
    return spec


def durasi_estimasi(teks):
    return max(2.0, round(len((teks or "").split()) * 0.38, 2))


def buat_dari_narasi(cfg, judul, baris, out, fmt="9:16", audio=None, batal=None, log=print):
    """baris = [{teks, durasi?}] atau [str]. Sutradara -> render animasi (durasi ngikut narasi)."""
    teks = [b["teks"] if isinstance(b, dict) else b for b in baris]
    spec = sutradara(cfg, judul, teks, batal=batal, log=log)
    for i, b in enumerate(baris):
        spec[i]["durasi"] = (b.get("durasi") if isinstance(b, dict) else None) or durasi_estimasi(teks[i])
    return buat_video(spec, out, fmt, audio=audio, log=log)


def buat_video(spec, out, fmt="9:16", audio=None, log=print):
    """spec = [{"tipe","durasi",**params}, ...] -> video flat-explainer di `out`."""
    W, H = UK[fmt]
    adegan = [TEMPLATE[s["tipe"]](max(1, round(s.get("durasi", 3) * FPS)), s, fmt) for s in spec]
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", f"{W}x{H}", "-framerate", str(FPS), "-i", "-"]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-shortest"] if audio else [])
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(out)]
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = sum(a.n for a in adegan)
    done = 0
    for a in adegan:
        for i in range(a.n):
            big = a.frame(i)
            img = big.convert("RGB").resize((W, H), Image.LANCZOS)
            fac = 1.0
            if i < FADE:
                fac = (i + 1) / (FADE + 1)
            if i >= a.n - FADE:
                fac = min(fac, (a.n - i) / (FADE + 1))
            if fac < 1:
                img = ImageEnhance.Brightness(img).enhance(fac)
            pipe.stdin.write(img.tobytes())
            done += 1
            if done % 30 == 0:
                log(f"  animasi {done}/{total} frame")
    pipe.stdin.close()
    pipe.wait()
    log(f"SELESAI -> {out}")
    return out


def render_klip(spec, frames, fmt, out, batal=None, log=None):
    """Render SATU adegan animasi ke file mp4 bisu sepanjang `frames` frame (buat disambung render.gabung)."""
    W, H = UK[fmt]
    ad = TEMPLATE.get(spec.get("tipe"), Sorot)(max(1, int(frames)), spec, fmt)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
           "-video_size", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-r", str(FPS), str(out)]
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    if batal:
        batal.daftar(pipe)
    try:
        for i in range(ad.n):
            if batal:
                batal.cek()
            img = ad.frame(i).convert("RGB").resize((W, H), Image.LANCZOS)
            fac = 1.0
            if i < FADE:
                fac = (i + 1) / (FADE + 1)
            if i >= ad.n - FADE:
                fac = min(fac, (ad.n - i) / (FADE + 1))
            if fac < 1:
                img = ImageEnhance.Brightness(img).enhance(fac)
            pipe.stdin.write(img.tobytes())
        pipe.stdin.close()
        pipe.wait()
    finally:
        if batal:
            batal.lepas(pipe)
    if pipe.returncode not in (0, None):
        raise RuntimeError(f"ffmpeg render_klip gagal (rc={pipe.returncode})")
    return out


def demo(out=None):
    out = out or (OUTPUT / "animasi-demo.mp4")
    spec = [
        {"tipe": "judul", "durasi": 2.5, "judul": "KENAPA ROKET\nBISA TERBANG?"},
        {"tipe": "roket", "durasi": 3.5, "label": "DORONGAN"},
        {"tipe": "orbit", "durasi": 3.0, "pusat": "bumi", "keliling": "bulan", "label": "ORBIT"},
        {"tipe": "sorot", "durasi": 3.0, "aset": "atom", "label": "PARTIKEL"},
        {"tipe": "maskot", "durasi": 2.5, "teks": "Keren kan?!"},
    ]
    return buat_video(spec, out, "9:16", log=lambda t: print(t, flush=True))


if __name__ == "__main__":
    demo(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
