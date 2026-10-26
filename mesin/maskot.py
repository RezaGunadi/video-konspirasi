"""Maskot channel "Si Kepo": makhluk bulat penasaran bertopi penjelajah dengan kaca pembesar (desain sendiri, SVG).

Lima pose (melambai, kaget, mikir, nunjuk, senang) + logo bulat untuk pojok video / foto profil. SVG dibuat dari
kode supaya warna & pose mudah diubah, lalu dirender ke PNG transparan dengan Edge headless. Pengguna boleh
mengganti PNG di folder maskot/ dengan gambar maskotnya sendiri (nama file sama).
"""
import os
import subprocess
import tempfile
from pathlib import Path

from .alat import AKAR

FOLDER = AKAR / "maskot"
POSE = ("melambai", "kaget", "mikir", "nunjuk", "senang")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
UKURAN = 600

GARIS = "#1B2A41"
BADAN, BADAN_GELAP, PERUT = "#2EC4B6", "#1E9E92", "#C8F5EF"
TOPI, TOPI_GELAP, PITA = "#F4C95D", "#D9A93A", "#8D5A3B"
MULUT, PIPI = "#7A1F2B", "#FF8FA3"


def _lengan(x1, y1, x2, y2, tangan=None):
    """Lengan tebal bergaris tepi + tangan bulat."""
    tx, ty = tangan or (x2, y2)
    return (f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{GARIS}" stroke-width="36" stroke-linecap="round" fill="none"/>'
            f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{BADAN}" stroke-width="22" stroke-linecap="round" fill="none"/>'
            f'<circle cx="{tx}" cy="{ty}" r="25" fill="{BADAN}" stroke="{GARIS}" stroke-width="7"/>')


def _mata(gaya="biasa"):
    if gaya == "tutup":  # senang: mata melengkung ^ ^
        return "".join(f'<path d="M{x - 34} {312} Q{x} {268} {x + 34} {312}" stroke="{GARIS}" stroke-width="10" '
                       f'stroke-linecap="round" fill="none"/>' for x in (248, 352))
    rx, ry, r = (46, 55, 14) if gaya == "besar" else (40, 46, 19)
    geser = {"atas": (-10, -16), "besar": (0, 0)}.get(gaya, (6, 6))
    hasil = ""
    for x, arah in ((248, 1), (352, -1)):
        px, py = x + geser[0] * (1 if gaya == "atas" else arah), 300 + geser[1]
        hasil += (f'<ellipse cx="{x}" cy="300" rx="{rx}" ry="{ry}" fill="#fff" stroke="{GARIS}" stroke-width="7"/>'
                  f'<circle cx="{px}" cy="{py}" r="{r}" fill="{GARIS}"/>'
                  f'<circle cx="{px + 7}" cy="{py - 8}" r="{max(4, r // 3)}" fill="#fff"/>')
    return hasil


def _alis(gaya):
    if gaya == "naik":
        return "".join(f'<path d="M{x - 30} 228 Q{x} 205 {x + 30} 228" stroke="{GARIS}" stroke-width="8" '
                       f'stroke-linecap="round" fill="none"/>' for x in (248, 352))
    if gaya == "mikir":
        return (f'<path d="M218 240 Q248 228 278 240" stroke="{GARIS}" stroke-width="8" stroke-linecap="round" fill="none"/>'
                f'<path d="M322 226 Q352 206 382 222" stroke="{GARIS}" stroke-width="8" stroke-linecap="round" fill="none"/>')
    if gaya == "yakin":
        return (f'<path d="M216 236 L280 244" stroke="{GARIS}" stroke-width="8" stroke-linecap="round"/>'
                f'<path d="M320 244 L384 236" stroke="{GARIS}" stroke-width="8" stroke-linecap="round"/>')
    return ""


def _mulut(gaya):
    if gaya == "o":
        return f'<ellipse cx="300" cy="382" rx="24" ry="30" fill="{MULUT}" stroke="{GARIS}" stroke-width="7"/>'
    if gaya == "datar":
        return f'<path d="M278 378 Q292 370 306 378 T334 376" stroke="{GARIS}" stroke-width="8" stroke-linecap="round" fill="none"/>'
    if gaya == "senyum":
        return f'<path d="M262 366 Q300 398 338 366" stroke="{GARIS}" stroke-width="9" stroke-linecap="round" fill="none"/>'
    # tertawa lebar: mulut terbuka + lidah
    return (f'<path d="M254 360 Q300 430 346 360 Z" fill="{MULUT}" stroke="{GARIS}" stroke-width="7" stroke-linejoin="round"/>'
            f'<path d="M278 392 Q300 380 322 392 Q312 410 300 410 Q288 410 278 392 Z" fill="#FF6B81"/>')


def _topi(miring=-7):
    return (f'<g transform="rotate({miring} 300 205)">'
            f'<ellipse cx="300" cy="214" rx="170" ry="30" fill="{TOPI_GELAP}" stroke="{GARIS}" stroke-width="8"/>'
            f'<path d="M182 210 C176 50 424 50 418 210 Z" fill="{TOPI}" stroke="{GARIS}" stroke-width="8" '
            f'stroke-linejoin="round"/>'
            f'<path d="M184 180 L416 180 L418 208 L182 208 Z" fill="{PITA}"/>'
            f'<path d="M222 150 Q232 112 270 98" stroke="#fff" stroke-width="11" stroke-linecap="round" fill="none" '
            f'opacity=".6"/>'
            f'<circle cx="300" cy="86" r="11" fill="{TOPI_GELAP}" stroke="{GARIS}" stroke-width="6"/></g>')


def _badan():
    return (f'<ellipse cx="240" cy="522" rx="50" ry="25" fill="{BADAN_GELAP}" stroke="{GARIS}" stroke-width="8"/>'
            f'<ellipse cx="360" cy="522" rx="50" ry="25" fill="{BADAN_GELAP}" stroke="{GARIS}" stroke-width="8"/>'
            f'<path d="M300 172 C405 172 452 262 452 362 C452 462 388 520 300 520 C212 520 148 462 148 362 '
            f'C148 262 195 172 300 172 Z" fill="{BADAN}" stroke="{GARIS}" stroke-width="9"/>'
            f'<ellipse cx="300" cy="430" rx="98" ry="78" fill="{PERUT}"/>'
            f'<ellipse cx="200" cy="350" rx="21" ry="12" fill="{PIPI}" opacity=".75"/>'
            f'<ellipse cx="400" cy="350" rx="21" ry="12" fill="{PIPI}" opacity=".75"/>')


def _lup(x, y, r=40):
    """Kaca pembesar: lensa di (x, y), gagang ke bawah-kanan."""
    return (f'<path d="M{x + r * 0.7:.0f} {y + r * 0.7:.0f} L{x + r * 1.7:.0f} {y + r * 1.7:.0f}" stroke="{GARIS}" '
            f'stroke-width="22" stroke-linecap="round"/>'
            f'<path d="M{x + r * 0.7:.0f} {y + r * 0.7:.0f} L{x + r * 1.7:.0f} {y + r * 1.7:.0f}" stroke="{PITA}" '
            f'stroke-width="11" stroke-linecap="round"/>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="#BDE8FF" fill-opacity=".55" stroke="{TOPI_GELAP}" stroke-width="12"/>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{GARIS}" stroke-width="4"/>'
            f'<path d="M{x - r * 0.45:.0f} {y - r * 0.2:.0f} Q{x - r * 0.35:.0f} {y - r * 0.5:.0f} {x - r * 0.05:.0f} '
            f'{y - r * 0.55:.0f}" stroke="#fff" stroke-width="7" stroke-linecap="round" fill="none"/>')


def svg_pose(pose):
    """SVG satu pose (kanvas 600×600, garis tepi putih seperti stiker + bayangan lembut)."""
    lapis = {"melambai": (_lengan(170, 392, 150, 448) + _lup(118, 392) + _badan() + _mata() + _mulut("tawa")
                          + _topi() + _lengan(432, 372, 505, 268) +
                          f'<path d="M548 228 Q566 252 552 280" stroke="{GARIS}" stroke-width="7" stroke-linecap="round" fill="none"/>'
                          f'<path d="M570 210 Q596 248 576 290" stroke="{GARIS}" stroke-width="7" stroke-linecap="round" fill="none"/>'),
             "kaget": (_badan() + _alis("naik") + _mata("besar") + _mulut("o") + _topi(4)
                       + _lengan(176, 382, 104, 262) + _lengan(424, 382, 496, 262) +
                       f'<path d="M524 70 L512 160" stroke="{MULUT}" stroke-width="18" stroke-linecap="round"/>'
                       f'<circle cx="508" cy="194" r="11" fill="{MULUT}"/>'
                       f'<path d="M560 98 L540 168" stroke="{MULUT}" stroke-width="13" stroke-linecap="round"/>'
                       f'<circle cx="535" cy="194" r="8" fill="{MULUT}"/>'
                       f'<path d="M160 230 Q148 256 160 266 Q172 256 160 230 Z" fill="#7FD3FF" stroke="{GARIS}" stroke-width="4"/>'),
             "mikir": (_lengan(170, 392, 150, 450) + _badan() + _alis("mikir") + _mata("atas") + _mulut("datar")
                       + _topi(-12) + _lengan(430, 410, 352, 412, (340, 404)) +
                       f'<circle cx="430" cy="226" r="11" fill="#fff" stroke="{GARIS}" stroke-width="5"/>'
                       f'<circle cx="458" cy="180" r="18" fill="#fff" stroke="{GARIS}" stroke-width="5"/>'
                       f'<circle cx="520" cy="104" r="62" fill="#fff" stroke="{GARIS}" stroke-width="7"/>'
                       f'<text x="520" y="132" text-anchor="middle" font-family="Arial Black, Arial" font-weight="900" '
                       f'font-size="84" fill="{BADAN_GELAP}">?</text>'),
             "nunjuk": (_lengan(172, 392, 158, 456) + _badan() + _alis("yakin") + _mata() + _mulut("senyum")
                        + _topi(-4) + _lengan(434, 370, 528, 330) +
                        f'<path d="M540 318 L584 300" stroke="{GARIS}" stroke-width="24" stroke-linecap="round"/>'
                        f'<path d="M540 318 L584 300" stroke="{BADAN}" stroke-width="11" stroke-linecap="round"/>'),
             "senang": (_badan() + _mata("tutup") + _mulut("tawa") + _topi(-9)
                        + _lengan(174, 380, 92, 318) + _lengan(426, 380, 508, 318)
                        + "".join(f'<path d="M{x} {y - s} L{x + s * .3:.0f} {y - s * .3:.0f} L{x + s} {y} L{x + s * .3:.0f} '
                                  f'{y + s * .3:.0f} L{x} {y + s} L{x - s * .3:.0f} {y + s * .3:.0f} L{x - s} {y} '
                                  f'L{x - s * .3:.0f} {y - s * .3:.0f} Z" fill="{TOPI}" stroke="{GARIS}" stroke-width="4"/>'
                                  for x, y, s in ((92, 196, 26), (520, 190, 22), (470, 60, 16))))}[pose]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{UKURAN}" height="{UKURAN}" viewBox="-20 -20 640 640">'
            '<defs><filter id="stiker" x="-10%" y="-10%" width="120%" height="120%">'
            '<feMorphology in="SourceAlpha" operator="dilate" radius="9" result="tebal"/>'
            '<feFlood flood-color="#ffffff"/><feComposite in2="tebal" operator="in" result="putih"/>'
            '<feDropShadow in="putih" dx="0" dy="7" stdDeviation="7" flood-color="#000" flood-opacity=".35" result="bayang"/>'
            '<feMerge><feMergeNode in="bayang"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
            f'<g filter="url(#stiker)" stroke-linejoin="round">{lapis}</g></svg>')


def svg_logo():
    """Logo bulat (wajah maskot) untuk pojok video dan foto profil channel."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{UKURAN}" height="{UKURAN}" viewBox="0 0 600 600">'
            '<defs><clipPath id="bulat"><circle cx="300" cy="300" r="276"/></clipPath></defs>'
            f'<circle cx="300" cy="300" r="290" fill="#fff"/><circle cx="300" cy="300" r="276" fill="{GARIS}"/>'
            f'<g clip-path="url(#bulat)" stroke-linejoin="round"><g transform="translate(0 60)">'
            f'{_badan()}{_mata()}{_mulut("tawa")}{_topi(-7)}</g></g>'
            f'<circle cx="300" cy="300" r="276" fill="none" stroke="{BADAN}" stroke-width="14"/></svg>')


def _render(svg, tujuan):
    """SVG → PNG transparan lewat Edge headless."""
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "m.html"
        html.write_text(f'<!doctype html><html><body style="margin:0;background:transparent;overflow:hidden">'
                        f'{svg}</body></html>', encoding="utf-8")
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                        f"--user-data-dir={tmp}\\profil", "--default-background-color=00000000",
                        f"--window-size={UKURAN},{UKURAN}", f"--screenshot={tujuan}", html.as_uri()],
                       capture_output=True, timeout=90)
    if not Path(tujuan).exists():
        raise RuntimeError(f"Edge gagal merender {Path(tujuan).name}")
    from PIL import Image
    gambar = Image.open(tujuan).convert("RGBA")
    kotak = gambar.getbbox()  # buang tepi transparan
    if kotak:
        gambar.crop(kotak).save(tujuan)
    return tujuan


def siapkan(paksa=False):
    """Pastikan maskot/<pose>.png dan maskot/logo.png ada (dibuat sekali; PNG buatan pengguna tidak ditimpa)."""
    FOLDER.mkdir(exist_ok=True)
    for pose in POSE:
        svg, png = FOLDER / f"{pose}.svg", FOLDER / f"{pose}.png"
        if paksa or not png.exists():
            svg.write_text(svg_pose(pose), encoding="utf-8")
            _render(svg_pose(pose), png)
    logo = FOLDER / "logo.png"
    if paksa or not logo.exists():
        (FOLDER / "logo.svg").write_text(svg_logo(), encoding="utf-8")
        _render(svg_logo(), logo)
    return {p: str(FOLDER / f"{p}.png") for p in (*POSE, "logo")}


def tersedia():
    return os.path.exists(EDGE) or all((FOLDER / f"{p}.png").exists() for p in (*POSE, "logo"))
