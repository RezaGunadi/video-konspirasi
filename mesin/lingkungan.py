"""Perbandingan 🆚 "satu foto, dua dunia": foto yang SAMA dibuat versi Bulan (abu-abu, langit hitam) dan versi Bumi
(berwarna, langit biru). Daratannya sama persis, latarnya beda — lebih meyakinkan daripada dua foto berbeda yang
"katanya mirip". Versi hasil olahan selalu diberi label ILUSTRASI di video.
"""
from pathlib import Path

import cv2
import numpy as np

GAYA = ("bulan", "bumi", "mars", "malam", "kuno", "asli")


def _langit(img):
    """Mask 0..1 area langit. Calon langit = bagian halus yang hitam pekat (Bulan), biru, atau putih mendung (Bumi).
    Langit dihitung PER KOLOM dari tepi atas sampai piksel bukan-langit pertama, lalu dibatasi tidak jauh di bawah
    cakrawala rata-rata — bayangan gelap modul pendaratan yang menyambung ke langit hitam tidak ikut jadi biru.
    Pinggiran gelap di sekitar astronot/bendera ditangani dengan bobot kegelapan. Mengembalikan (mask, porsi)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(np.int16), hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
    tinggi, lebar = img.shape[:2]
    abu = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    rata = cv2.GaussianBlur(abu, (0, 0), 3)
    simpang = np.sqrt(np.maximum(cv2.GaussianBlur(abu * abu, (0, 0), 3) - rata * rata, 0))
    halus = simpang < 14
    # foto hasil scan cetakan: langit Bulan abu-abu gelap, bukan hitam pekat — ambangnya ikut kecerahan bagian atas
    atas = float(np.median(v[: max(2, tinggi // 12)]))
    gelap = v < (max(40, atas + 28) if atas < 75 else 40)
    calon =(gelap | ((h > 85) & (h < 135) & (s > 35) & (v > 80)) | ((v > 195) & (s < 45))) & halus
    calon = cv2.morphologyEx(calon.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    # panjang langit tiap kolom dari atas
    bukan = ~calon
    batas = np.where(bukan.any(axis=0), bukan.argmax(axis=0), tinggi).astype(np.float32)
    ada = batas > tinggi * 0.03
    if ada.mean() < 0.3:  # sebagian besar kolom tidak punya langit di atas: tidak ada cakrawala
        return np.zeros((tinggi, lebar, 1), np.float32), 0.0
    cakrawala = float(np.median(batas[ada]))
    batas = np.minimum(batas, cakrawala + tinggi * 0.04)
    batas = cv2.medianBlur(batas.astype(np.uint16).reshape(1, -1), 5).reshape(-1).astype(np.float32)
    baris = np.arange(tinggi, dtype=np.float32)[:, None]
    mask = (baris < batas[None, :]).astype(np.float32)
    langit_gelap = float(v[mask > 0].mean()) < 45 if mask.any() else False
    if langit_gelap:
        # pinggiran: piksel gelap di dekat batas langit ikut diganti sebanding kegelapannya
        dekat = cv2.dilate(mask, np.ones((9, 9), np.uint8))
        bobot = np.clip((70.0 - v) / 70.0, 0, 1).astype(np.float32)
        mask = np.maximum(mask, dekat * bobot * (baris < (batas[None, :] + 8)))
    mask = cv2.GaussianBlur(mask, (0, 0), 1.5)
    return mask[..., None], float((mask > 0.5).mean())


def ada_cakrawala(src):
    """Foto layak untuk "satu foto, dua dunia" kalau ada daratan di bawah dan langit di atas (bukan foto bulatan
    Bulan penuh atau close-up tanpa langit — yang pernah menghasilkan "bola oranye di langit biru")."""
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        return False
    skala = min(1.0, 900 / max(img.shape[:2]))
    img = cv2.resize(img, None, fx=skala, fy=skala, interpolation=cv2.INTER_AREA) if skala < 1 else img
    mask, porsi = _langit(img)
    m = mask[..., 0] > 0.5
    h = m.shape[0]
    atas, bawah = float(m[: max(1, h // 10)].mean()), float(m[-max(1, h // 5):].mean())
    return 0.08 <= porsi <= 0.7 and atas > 0.6 and bawah < 0.05


def _gradasi(h, w, atas, bawah):
    """Gradasi vertikal (BGR) dari warna `atas` ke `bawah`."""
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    atas, bawah = np.array(atas, np.float32), np.array(bawah, np.float32)
    return np.broadcast_to(atas * (1 - t) + bawah * t, (h, w, 3)).copy()


def _gradasi_langit(h, w):
    """Langit biru siang: biru tua di atas, biru pucat di dekat cakrawala (BGR)."""
    return _gradasi(h, w, (175, 105, 35), (235, 215, 180))


# Warna tanah per dunia (BGR gelap → terang) dan warna langitnya (atas → cakrawala).
_DUNIA = {
    "bumi": {"tanah": ((22, 42, 78), (118, 186, 242)), "langit": ((175, 105, 35), (235, 215, 180))},
    "mars": {"tanah": ((15, 28, 70), (80, 130, 215)), "langit": ((120, 160, 200), (165, 200, 230))},
}


def _warnai_tanah(img, abu, hsv0, gelap, terang):
    """Foto abu-abu diwarnai seperti tanah dunia lain. Yang sangat terang (baju astronot) tetap putih, yang aslinya
    berwarna (bendera) memakai warna aslinya: hanya daratannya yang berubah."""
    L = np.clip(abu ** 0.9, 0, 1)
    gelap, terang = np.array(gelap, np.float32), np.array(terang, np.float32)
    darat = gelap * (1 - L[..., None]) + terang * L[..., None]
    putih = np.clip((L - 0.72) / 0.2, 0, 1)[..., None]
    darat = darat * (1 - putih) + (L[..., None] * 255) * putih
    # warna asli dipertahankan hanya kalau JAUH lebih jenuh dari warna umum foto itu: bendera merah tetap merah, tapi
    # cast biru foto hasil scan (bayangan kebiruan) tidak ikut — dulu jadi bercak biru di tanah pasir
    terang = hsv0[..., 2] > 60
    umum = float(np.percentile(hsv0[..., 1][terang], 90)) if terang.any() else 0.0
    jenuh = hsv0[..., 1].astype(np.float32) * terang
    asli = np.clip((jenuh - max(50.0, umum + 20)) / 60, 0, 1)[..., None]
    hsv_hidup = hsv0.astype(np.float32)
    hsv_hidup[..., 1] = np.clip(hsv_hidup[..., 1] * 1.2, 0, 255)
    return darat * (1 - asli) + cv2.cvtColor(hsv_hidup.astype(np.uint8), cv2.COLOR_HSV2BGR) * asli


def ubah(src, gaya, tujuan, maks=1800, dari=None):
    """Simpan versi `gaya` dari foto `src` ke `tujuan` (jpg): bulan (abu-abu, langit hitam), bumi (berwarna, langit
    biru), mars (tanah merah karat, langit jingga pucat), malam (gelap kebiruan, langit malam berbintang), kuno (foto
    tua sepia berbintik), asli (tanpa perubahan). Mengembalikan path."""
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"foto tidak bisa dibaca: {src}")
    skala = min(1.0, maks / max(img.shape[:2]))
    if skala < 1:
        img = cv2.resize(img, None, fx=skala, fy=skala, interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    if gaya not in GAYA or gaya == "asli":
        cv2.imwrite(str(tujuan), img, [cv2.IMWRITE_JPEG_QUALITY, 93])
        return Path(tujuan)
    abu = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    if gaya == "kuno":  # foto tua: sepia, butiran, sudut menggelap — tanpa mengganti langit
        L = np.clip((abu - 0.5) * 0.9 + 0.52, 0, 1)
        sepia = np.dstack([L * 170 + 20, L * 205 + 25, L * 225 + 30])
        acak = np.random.default_rng(7).normal(0, 9, (h, w, 1)).astype(np.float32)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        jarak = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        vinyet = np.clip(1.15 - 0.45 * jarak ** 2, 0.45, 1)[..., None]
        cv2.imwrite(str(tujuan), np.clip((sepia + acak) * vinyet, 0, 255).astype(np.uint8),
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        return Path(tujuan)
    mask, porsi = _langit(img)
    if porsi < 0.02 or porsi > 0.85:  # tidak ada cakrawala yang jelas: hanya warna daratannya yang diubah
        mask = np.zeros((h, w, 1), np.float32)
    hsv0 = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # saturasi dari piksel yang cukup terang saja: langit hitam punya saturasi acak yang tinggi
    terang = hsv0[..., 2] > 60
    warna_asli = float(hsv0[..., 1][terang].mean()) > 45 if terang.any() else False
    if gaya == "bulan":
        # regolit abu-abu dingin dengan kontras tinggi, langit hitam pekat
        L = np.clip((abu - 0.5) * 1.25 + 0.47, 0, 1)
        darat = np.dstack([L * 245, L * 238, L * 232]).astype(np.float32)
        langit = np.full((h, w, 3), 6, np.float32)
    elif gaya == "malam":
        darat = img.astype(np.float32) * np.array([0.42, 0.33, 0.28], np.float32)  # gelap kebiruan (BGR)
        langit = _gradasi(h, w, (38, 14, 4), (70, 36, 16))
        bintang = np.random.default_rng(3).random((h, w)) > 0.9985
        langit[bintang] = 235
        langit = cv2.GaussianBlur(langit, (0, 0), 0.6)
    else:  # bumi / mars
        d = _DUNIA[gaya]
        # foto dari Bulan/Mars SELALU diwarnai jadi tanah Bumi (foto scan sering punya cast warna biru yang terbaca
        # "berwarna"); hanya foto Bumi asli yang warnanya dipertahankan
        if warna_asli and gaya == "bumi" and dari not in ("bulan", "mars"):
            hsv = hsv0.astype(np.float32)
            hsv[..., 1] = np.clip(hsv[..., 1] * 1.25, 0, 255)
            darat = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
        else:
            darat = _warnai_tanah(img, abu, hsv0, *d["tanah"])
        langit = _gradasi(h, w, *d["langit"])
    hasil = darat * (1 - mask) + langit * mask
    cv2.imwrite(str(tujuan), np.clip(hasil, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 93])
    return Path(tujuan)
