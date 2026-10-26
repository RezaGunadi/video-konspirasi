"""Foto dibuat "hidup" (2.5D parallax): model Depth Anything V2 (kecil, jalan di CPU) menebak kedalaman tiap piksel,
lalu kamera bergerak sehingga benda dekat bergeser lebih jauh daripada latar — terasa seperti klip video pendek,
bukan sekadar foto di-zoom. Dipakai untuk shot foto kalau opsi "animasi" = "hidup".

GPU laptop ini (GTX 1650 Ti, 4 GB) tidak cukup untuk model pembuat video AI, jadi parallax adalah pilihan yang
realistis: ±0,5 detik per foto untuk kedalaman + beberapa detik per shot untuk merender gerakannya.
"""
import os
import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

from .alat import CACHE, FFMPEG, HF_CACHE, NO_WINDOW, Dibatalkan, hash_pendek

F_DALAM = CACHE / "kedalaman"
F_DALAM.mkdir(parents=True, exist_ok=True)
F_KLIP = CACHE / "hidup"
F_KLIP.mkdir(parents=True, exist_ok=True)
MODEL = "depth-anything/Depth-Anything-V2-Small-hf"

_model = None
_kunci = threading.Lock()


def tersedia():
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _muat():
    global _model
    if _model is None:
        os.environ.setdefault("HF_HOME", str(HF_CACHE))
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        torch.set_num_threads(max(2, (os.cpu_count() or 4) // 2))
        _model = (AutoImageProcessor.from_pretrained(MODEL),
                  AutoModelForDepthEstimation.from_pretrained(MODEL).eval())
    return _model


def kedalaman(src):
    """Peta kedalaman 0..1 (1 = paling dekat) seukuran foto (maks 1024 px), di-cache per isi file."""
    data = Path(src).read_bytes()
    cache = F_DALAM / f"{hash_pendek(data.hex()[:20000] + str(len(data)))}.png"
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"foto tidak bisa dibaca: {src}")
    h, w = img.shape[:2]
    skala = min(1.0, 1024 / max(h, w))
    uk = (max(1, int(w * skala)), max(1, int(h * skala)))
    if cache.exists():
        d = cv2.imread(str(cache), cv2.IMREAD_UNCHANGED)
        if d is not None and d.shape[:2] == (uk[1], uk[0]):
            return d.astype(np.float32) / 65535
    import torch
    with _kunci:
        proses, model = _muat()
        rgb = cv2.cvtColor(cv2.resize(img, uk, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            keluar = model(**proses(images=rgb, return_tensors="pt")).predicted_depth[0].numpy()
    d = cv2.resize(keluar.astype(np.float32), uk, interpolation=cv2.INTER_CUBIC)
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
    # dihaluskan: tepi benda yang tajam di peta kedalaman membuat gambar "sobek" saat kamera bergerak
    d = cv2.GaussianBlur(d, (0, 0), max(1.5, 0.006 * max(uk)))
    cv2.imwrite(str(cache), (d * 65535).astype(np.uint16))
    return d


def _halus(t):
    return t * t * (3 - 2 * t)  # ease in-out


# Gerak kamera: fungsi t (0..1) → (zoom, geser_x, geser_y, dolly). geser = pergeseran benda paling dekat relatif
# terhadap latar (pecahan lebar layar); dolly = benda dekat membesar lebih cepat daripada latar.
def _gerak(nama, t, acak):
    """(zoom, geser_x, geser_y, dolly) pada waktu t (0..1). Geseran kecil disengaja: area di belakang benda depan
    yang ikut terbuka hanyalah tambalan (inpaint), jadi tidak boleh terlihat lebar."""
    e = _halus(t)
    if nama == "masuk":
        return 1.0 + 0.05 * e, 0.0, 0.0, 0.06 * e
    if nama == "keluar":
        return 1.05 - 0.05 * e, 0.0, 0.0, 0.06 * (1 - e)
    if nama == "kanan":
        return 1.03, 0.02 - 0.04 * e, 0.0, 0.02
    if nama == "kiri":
        return 1.03, -0.02 + 0.04 * e, 0.0, 0.02
    if nama == "naik":
        return 1.03, 0.0, -0.018 + 0.036 * e, 0.02
    if nama == "turun":
        return 1.03, 0.0, 0.018 - 0.036 * e, 0.02
    if nama == "diagonal":  # orbit pelan
        return 1.02 + 0.03 * e, 0.02 * np.cos(np.pi * e), 0.01 * np.sin(np.pi * e), 0.04 * e
    if nama == "hentak":  # dorong cepat lalu melambat
        c = 1 - np.exp(-t * 7)
        return 1.0 + 0.08 * c + 0.02 * t, 0.0, 0.0, 0.07 * c
    if nama == "goyang":  # kamera dipegang tangan
        return (1.04 + 0.02 * e, 0.005 * np.sin(t * 9.1 + acak) + 0.003 * np.sin(t * 23.7),
                0.004 * np.cos(t * 7.3 + acak), 0.03 * e)
    return 1.0 + 0.04 * e, 0.0, 0.0, 0.04 * e


def _lapisan(img, d):
    """Pisahkan foto jadi lapisan DEPAN (benda dekat, dengan alpha halus) dan BELAKANG (foto yang bagian
    tertutupnya ditambal/inpaint). Menggeser per piksel menurut kedalaman membuat tepi benda melar seperti karet;
    dua lapisan yang bergerak dengan kecepatan beda terlihat bersih, seperti parallax buatan editor dokumenter.
    None kalau tidak ada benda depan yang jelas (pemandangan datar, dokumen)."""
    h, w = d.shape
    d8 = (d * 255).astype(np.uint8)
    ambang, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    depan = (d8 > max(ambang, 60)).astype(np.uint8)
    k = max(3, int(0.006 * max(h, w)) | 1)
    depan = cv2.morphologyEx(depan, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    depan = cv2.morphologyEx(depan, cv2.MORPH_CLOSE, np.ones((3 * k, 3 * k), np.uint8))
    porsi = float(depan.mean())
    if not 0.04 <= porsi <= 0.6:
        return None
    # lapisan depan diperlebar sedikit (ikut membawa tepi bendanya), dan HANYA area itu yang ditambal di lapisan
    # belakang: saat kamera diam tidak ada tambalan yang terlihat; saat bergerak hanya pita selebar geserannya
    r = max(5, int(0.012 * max(h, w)))
    depan = cv2.dilate(depan, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r)))
    alpha = cv2.GaussianBlur(depan.astype(np.float32), (0, 0), max(2.0, 0.003 * max(h, w)))
    lubang = cv2.dilate(depan, np.ones((5, 5), np.uint8))
    kecil = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    lk = cv2.resize(lubang, (w // 2, h // 2), interpolation=cv2.INTER_NEAREST)
    tambal = cv2.resize(cv2.inpaint(kecil, lk, 7, cv2.INPAINT_TELEA), (w, h), interpolation=cv2.INTER_CUBIC)
    lb = cv2.GaussianBlur(lubang.astype(np.float32), (0, 0), 2)[..., None]
    belakang = (img * (1 - lb) + tambal * lb).astype(np.uint8)
    return belakang, alpha


def animasikan(src, frames, W, H, gerak, tujuan=None, fps=30, tutup_bawah=False, batal=None, encoder=None):
    """Klip mp4 (tanpa audio) berdurasi `frames` frame dari satu foto dengan gerak kamera 2.5D. Di-cache."""
    tujuan = Path(tujuan) if tujuan else F_KLIP / (
        f"{hash_pendek('|'.join(map(str, [Path(src).stat().st_size, src, frames, W, H, gerak, tutup_bawah, 6])))}.mp4")
    if tujuan.exists() and tujuan.stat().st_size > 1000:
        return tujuan
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"foto tidak bisa dibaca: {src}")
    d = kedalaman(src)
    if tutup_bawah:  # subtitle/teks tertanam di bawah: dibuang
        img, d = img[: int(img.shape[0] * 0.78)], d[: int(d.shape[0] * 0.78)]
    # kanvas sedikit lebih besar dari layar (ruang untuk bergerak); foto & kedalamannya memenuhi kanvas
    m = 1.12
    Bw, Bh = int(W * m), int(H * m)
    s = max(Bw / img.shape[1], Bh / img.shape[0])
    nw, nh = max(Bw, int(img.shape[1] * s + 0.5)), max(Bh, int(img.shape[0] * s + 0.5))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    d = cv2.resize(d, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x0, y0 = (nw - Bw) // 2, (nh - Bh) // 2
    img, d = img[y0:y0 + Bh, x0:x0 + Bw], d[y0:y0 + Bh, x0:x0 + Bw]
    lapis = _lapisan(img, d)
    cx, cy = Bw / 2, Bh / 2
    acak = float(int(hash_pendek(str(src))[:4], 16) % 628) / 100

    def matriks(zoom, gx, gy):  # kanvas → layar: zoom di tengah lalu geser (pecahan layar)
        return np.float32([[zoom, 0, W / 2 - zoom * cx + gx * W], [0, zoom, H / 2 - zoom * cy + gy * H]])

    enc = encoder or ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17"]
    proses = subprocess.Popen([FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                               "-r", str(fps), "-i", "-", *enc, "-pix_fmt", "yuv420p", "-an", str(tujuan)],
                              stdin=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        for f in range(frames):
            if batal and f % 15 == 0:
                batal.cek()
            t = f / max(1, frames - 1)
            zoom, sx, sy, dolly = _gerak(gerak, t, acak)
            if lapis is None:  # satu lapisan: gerak kamera halus (presisi float, tanpa getar zoompan)
                bingkai = cv2.warpAffine(img, matriks(zoom, sx * 0.5, sy * 0.5), (W, H), flags=cv2.INTER_LINEAR,
                                         borderMode=cv2.BORDER_REFLECT)
            else:
                belakang, alpha = lapis
                # latar bergeser sedikit berlawanan arah, benda depan bergeser & membesar lebih cepat
                mb = matriks(zoom, -sx * 0.25, -sy * 0.25)
                md = matriks(zoom * (1 + dolly), sx * 0.5, sy * 0.5)
                b = cv2.warpAffine(belakang, mb, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                dp = cv2.warpAffine(img, md, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                a = cv2.warpAffine(alpha, md, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
                bingkai = (dp * a + b * (1 - a)).astype(np.uint8)
            proses.stdin.write(bingkai.tobytes())
        proses.stdin.close()
        if proses.wait(timeout=300) != 0:
            raise RuntimeError("ffmpeg gagal menyimpan klip parallax")
    except (Dibatalkan, Exception):
        proses.kill()
        Path(tujuan).unlink(missing_ok=True)
        raise
    return tujuan
