"""Benda dipotong dari latarnya seperti stiker potongan, dengan model ISNet ("isnet-general-use", ONNX ±180 MB, jalan
di CPU lewat onnxruntime yang sudah terpasang bersama faster-whisper). Dipakai untuk stiker analogi ("setara dengan
menumpuk 1.600 gajah"): potongan gajah UTUH ditumpuk menjadi gunungan, bukan foto berbingkai yang ditumpuk (yang
kelihatan seperti tumpukan foto wajah gajah, bukan tumpukan gajah).

Sekaligus menjadi penyaring "benda utuh" untuk topik apa pun: foto close-up (wajah gajah), benda yang menempel di
tepi foto (gunung, lanskap), atau benda yang terlalu kecil di tengah pemandangan ditolak dengan alasan yang jelas.
"""
import json
import threading
from pathlib import Path

import numpy as np

from .alat import CACHE, TOOLS, hash_pendek, unduh

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
F_MODEL = TOOLS / "rembg" / "isnet-general-use.onnx"
F_POTONG = CACHE / "potong"
F_POTONG.mkdir(parents=True, exist_ok=True)
SISI = 1024  # ukuran masukan ISNet

_sesi = None
_kunci = threading.Lock()


def tersedia():
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _muat():
    global _sesi
    if _sesi is None:
        import onnxruntime as ort
        F_MODEL.parent.mkdir(parents=True, exist_ok=True)
        if not unduh(MODEL_URL, F_MODEL, batas_mb=250):
            raise RuntimeError("model pemotong latar (ISNet) gagal diunduh")
        _sesi = ort.InferenceSession(str(F_MODEL), providers=["CPUExecutionProvider"])
    return _sesi


def topeng(rgb):
    """Peta "benda depan" 0..1 seukuran foto (array RGB uint8)."""
    import cv2
    x = cv2.resize(rgb, (SISI, SISI), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = x / max(float(x.max()), 1e-6) - 0.5  # normalisasi ISNet: mean 0.5, std 1
    with _kunci:
        sesi = _muat()
        keluar = sesi.run(None, {sesi.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    lo, hi = float(keluar.min()), float(keluar.max())
    m = (keluar - lo) / max(hi - lo, 1e-6)
    return cv2.resize(m, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)


def _nilai(m):
    """(alasan_tolak | None, kotak) dari topeng: benda harus cukup besar, terpisah dari latar, dan tidak terpotong
    tepi foto. Kotak = (x0, y0, x1, y1) benda utama."""
    import cv2
    h, w = m.shape
    biner = (m > 0.5).astype(np.uint8)
    n, label, stat, _ = cv2.connectedComponentsWithStats(biner, connectivity=8)
    if n < 2:
        return "tidak ada benda yang terpisah dari latar", None
    luas = stat[1:, cv2.CC_STAT_AREA]
    terbesar = int(luas.max())
    # bagian benda yang sama (kaki gajah yang terpisah oleh bayangan) ikut; bintik kecil di latar dibuang
    simpan = [i + 1 for i, a in enumerate(luas) if a >= 0.12 * terbesar]
    biner = np.isin(label, simpan).astype(np.uint8)
    porsi = biner.mean()
    if porsi < 0.04:
        return f"bendanya terlalu kecil di foto ({porsi:.0%})", None
    if porsi > 0.80:
        return "latar tidak bisa dipisahkan (foto penuh benda/lanskap)", None
    ys, xs = np.nonzero(biner)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    # menempel tepi foto = bendanya terpotong (close-up wajah, gunung, lanskap). Satu sisi masih wajar
    # (kaki terpotong di bawah, benda di atas meja); dua sisi atau satu sisi lebar berarti tidak utuh.
    sisi = {"atas": biner[:2].any(0).mean(), "bawah": biner[-2:].any(0).mean(),
            "kiri": biner[:, :2].any(1).mean(), "kanan": biner[:, -2:].any(1).mean()}
    kena = [k for k, v in sisi.items() if v > 0.06]
    if len(kena) >= 2 or max(sisi.values()) > 0.35:
        return f"bendanya terpotong tepi foto ({', '.join(kena) or max(sisi, key=sisi.get)})", None
    # topeng yang ragu-ragu (banyak piksel setengah transparan) = model tidak yakin mana bendanya
    ragu = ((m > 0.15) & (m < 0.85)).sum() / max(biner.sum(), 1)
    if ragu > 0.45:
        return "batas benda tidak jelas", None
    return None, (x0, y0, x1, y1)


def potong(src):
    """Potong benda utama dari foto. Mengembalikan (png_transparan | None, alasan_tolak | None); hasil & penolakan
    di-cache per isi file."""
    from PIL import Image, ImageOps
    data = Path(src).read_bytes()
    kunci = hash_pendek(data.hex()[:20000] + str(len(data)))
    png, catatan = F_POTONG / f"{kunci}.png", F_POTONG / f"{kunci}.json"
    if png.exists():
        return str(png), None
    if catatan.exists():
        return None, json.loads(catatan.read_text(encoding="utf-8")).get("alasan")
    try:
        foto = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    except Exception as e:
        return None, f"foto tidak bisa dibaca ({e})"
    foto.thumbnail((1600, 1600), Image.LANCZOS)
    rgb = np.asarray(foto)
    m = topeng(rgb)
    alasan, kotak = _nilai(m)
    if alasan:
        catatan.write_text(json.dumps({"alasan": alasan}, ensure_ascii=False), encoding="utf-8")
        return None, alasan
    import cv2
    # tepi dirapikan: nilai ragu di pinggir benda dipertegas supaya tidak ada "kabut" latar di sekeliling potongan
    alfa = np.clip((m - 0.25) / 0.5, 0, 1)
    alfa = cv2.GaussianBlur(alfa, (0, 0), 0.8)
    x0, y0, x1, y1 = kotak
    pad = int(0.02 * max(rgb.shape[:2]))
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(rgb.shape[1], x1 + pad), min(rgb.shape[0], y1 + pad)
    rgba = np.dstack([rgb, (alfa * 255).astype(np.uint8)])[y0:y1, x0:x1]
    sementara = png.with_suffix(".part.png")
    Image.fromarray(rgba, "RGBA").save(sementara)
    sementara.replace(png)
    return str(png), None
