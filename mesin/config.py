"""Pengaturan aplikasi (data/config.json)."""
import threading

from .alat import DATA, baca_json, tulis_json

PATH = DATA / "config.json"
DISCLAIMER_BAWAAN = ("Video ini membahas teori konspirasi, legenda, dan misteri untuk hiburan dan wawasan. "
                     "Isinya bukan fakta yang sudah terbukti. Tetap cek sumber terpercaya.")
_lock = threading.Lock()

BAWAAN = {
    "ollama_url": "http://127.0.0.1:11434",
    # Model yang sama dengan Sosmed AI (num_ctx sama) agar tidak dimuat ulang.
    "model": "sosmed-ai",
    "pexels_key": "",
    "pixabay_key": "",
    "pantau_input": True,  # file .txt di folder input/ otomatis diproses
    # Maksimal putaran AI menilai gambar per adegan (0 = otomatis: 3 di mode video, 4 di klasik). Mini PC tanpa GPU: 2.
    "putaran_gambar": 0,
    # Gambar dari seluruh web (Bing Images via Edge headless): "tidak" / "berlisensi" (filter bebas dipakai) /
    # "semua" (termasuk gambar berhak cipta — risiko klaim di YouTube/TikTok ditanggung pemilik channel).
    "sumber_web": "tidak",
    # Pengaturan bawaan untuk proyek baru (form GUI ingat pilihan terakhir).
    "default": {
        "mode": "tulis",        # tulis = AI menulis naskah dari teks; bacakan = teks dibacakan apa adanya
        "format": "9:16",       # 9:16 (Shorts/Reels/TikTok) atau 16:9 (YouTube)
        "durasi": 60,           # detik target (mode tulis)
        "suara": "id-ID-ArdiNeural",
        "kecepatan": -5,        # persen
        "nada": -6,             # Hz
        "subtitle": True,
        "musik": True,          # acak dari folder musik/ kalau ada isinya
        "volume_musik": 12,     # persen
        "cek_gambar": True,     # AI melihat kandidat footage lalu memilih yang paling pas
        "cek_naskah": False,    # berhenti dulu agar naskah bisa diperiksa/diedit
        "riset": True,          # ambil fakta dari Wikipedia sebelum menulis
        "gaya": "misterius",    # misterius = gelap, grain, vignette; cerah = dokumenter terang + tulisan besar; natural
        "isi_layar": "crop",    # crop = penuh layar; blur = footage utuh dengan latar blur
        # meyakinkan = host ngobrol ke kamera, menyambungkan fakta yang tercatat jadi kecurigaan; twist = membongkar
        # kasus; bangun_teori = bukti demi bukti; seimbang = edukatif; edukasi = fakta sains seru
        "gaya_naskah": "meyakinkan",
        "suara_alami": True,    # jeda antarkalimat seperti narator manusia + warna rekaman (EQ, kompresi, ruang)
        "animasi": "hidup",     # hidup = klip video asli diutamakan + foto dibuat bergerak 2.5D; zoom = zoom/pan biasa
        # video_stiker = mayoritas klip video (±3,5 detik per potongan), foto yang tepat ditempel sebagai stiker di
        # atasnya, foto layar penuh maksimal 3 detik; klasik = foto & video layar penuh 4-7 detik per gambar
        "visual": "video_stiker",
        "maskot": True,         # maskot "Si Kepo" bereaksi di momen penting + logo kecil di pojok (folder maskot/)
        "cta": "Tulis pendapatmu di kolom komentar, like, dan subscribe kalau mau kita bongkar teori ini lebih dalam.",
        # Format "keduanya": 1 video panjang 16:9 + beberapa reels 9:16 berisi teaser (naskah beda, tidak membongkar
        # jawabannya) yang diakhiri ajakan menonton video lengkapnya.
        "jumlah_reels": 3,
        "durasi_reels": 45,
        "cta_reels": "Jawabannya ada di video lengkapnya. Tonton sekarang lewat link di bawah.",
        "disclaimer": "awal",   # awal = teks 5 detik pertama; akhir = kartu dibacakan; keduanya; tidak
        "teks_disclaimer": DISCLAIMER_BAWAAN,
    },
}


def muat():
    with _lock:
        c = baca_json(PATH, {}) or {}
    hasil = {**BAWAAN, **c}
    hasil["default"] = {**BAWAAN["default"], **(c.get("default") or {})}
    return hasil


def simpan(perubahan):
    with _lock:
        c = baca_json(PATH, {}) or {}
        for k, v in perubahan.items():
            if k == "default" and isinstance(v, dict):
                c["default"] = {**(c.get("default") or {}), **v}
            elif k in BAWAAN:
                c[k] = v
        tulis_json(PATH, c)
    return muat()


def publik():
    """Config untuk GUI: API key tidak dikirim utuh."""
    c = muat()
    for k in ("pexels_key", "pixabay_key"):
        v = c.get(k) or ""
        c[k] = (v[:4] + "…" + v[-3:]) if len(v) > 8 else ("•••" if v else "")
        c[k + "_ada"] = bool(v)
    return c
