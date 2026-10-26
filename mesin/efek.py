"""Desain suara buatan sendiri (bebas hak cipta): musik latar mencekam dan efek transisi.

Semua disintesis dengan numpy lalu disimpan sebagai WAV 48 kHz stereo.
"""
import re
import wave

import numpy as np

from .alat import CACHE

SR = 48000


def _simpan(path, stereo):
    """stereo: array (n, 2) float -1..1 → WAV 16-bit."""
    data = np.clip(stereo, -1, 1)
    data = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    return path


def _lowpass(x, potong):
    """Lowpass sederhana lewat FFT (cukup untuk tekstur angin/noise)."""
    f = np.fft.rfft(x)
    frek = np.fft.rfftfreq(len(x), 1 / SR)
    f[frek > potong] *= 0
    return np.fft.irfft(f, len(x))


def _bandpass(x, bawah, atas):
    f = np.fft.rfft(x)
    frek = np.fft.rfftfreq(len(x), 1 / SR)
    f[(frek < bawah) | (frek > atas)] *= 0
    return np.fft.irfft(f, len(x))


def musik_misteri():
    """Ambient gelap 3 menit (diulang otomatis saat mixing): dengung rendah yang berdenyut pelan, angin,
    pad disonan (interval setengah nada) yang muncul-hilang, denting tinggi samar, dan detak rendah jarang."""
    tujuan = CACHE / "musik-misteri-v2.wav"
    if tujuan.exists():
        return tujuan
    rng = np.random.default_rng(7)
    d = 180
    t = np.arange(d * SR) / SR
    pudar = np.minimum(1, np.minimum(t / 3, (d - t) / 3))  # ujung loop halus

    def lfo(f, fase=0.0, dasar=0.6, dalam=0.4):
        return dasar + dalam * np.sin(2 * np.pi * f * t + fase)

    kiri = np.zeros_like(t)
    kanan = np.zeros_like(t)
    # 1) dengung rendah (A1 + sedikit detune → berdenyut), quinta di atasnya
    for f, a, fase in ((55.0, 0.30, 0), (55.35, 0.22, 1.3), (82.4, 0.12, 2.1), (110.2, 0.06, 0.4)):
        g = a * np.sin(2 * np.pi * f * t + fase) * lfo(0.05 + f / 4000, fase)
        kiri += g
        kanan += g * 0.92
    # 2) angin: noise diredam ke frekuensi rendah, naik-turun pelan, sedikit beda kiri/kanan
    for sisi, fase in ((0, 0.0), (1, 1.7)):
        angin = _lowpass(rng.standard_normal(len(t)), 420)
        angin = angin / (np.abs(angin).max() + 1e-9) * 0.16 * lfo(0.031, fase, 0.55, 0.45)
        if sisi == 0:
            kiri += angin
        else:
            kanan += angin
    # 3) pad disonan (A3 & A#3 + E4) yang muncul tiap ±24 detik → rasa tegang
    tegang = np.clip(np.sin(2 * np.pi * t / 24.0 - 1.2), 0, None) ** 2
    for f, a in ((220.0, 0.05), (233.08, 0.045), (329.6, 0.03)):
        g = a * np.sin(2 * np.pi * f * t) * tegang
        kiri += g
        kanan += g * 0.85
    # 4) denting tinggi samar yang bergetar
    denting = 0.012 * np.sin(2 * np.pi * 1318.5 * t) * lfo(4.5, 0, 0.5, 0.5) * lfo(0.07, 0.8, 0.5, 0.5)
    kiri += denting * 0.6
    kanan += denting
    # 5) detak rendah jarang (tiap 7,5 detik): dua denyut seperti jantung
    for mulai in np.arange(4.0, d - 2, 7.5):
        for geser, kuat in ((0.0, 1.0), (0.28, 0.7)):
            i0 = int((mulai + geser) * SR)
            n = int(0.35 * SR)
            tt = np.arange(n) / SR
            detak = kuat * 0.25 * np.sin(2 * np.pi * (48 - 12 * tt) * tt) * np.exp(-tt * 14)
            kiri[i0:i0 + n] += detak
            kanan[i0:i0 + n] += detak
    stereo = np.stack([kiri, kanan], axis=1) * pudar[:, None]
    stereo = stereo / (np.abs(stereo).max() + 1e-9) * 0.6
    return _simpan(tujuan, stereo)


def musik_cerah():
    """Musik latar dokumenter yang tenang & optimis (untuk video sains/fakta): pad hangat dengan progresi
    C – G – Am – F (8 detik per akor), petikan arpeggio lembut, dan denyut bass pelan. 128 detik, diulang saat mixing."""
    tujuan = CACHE / "musik-cerah-v1.wav"
    if tujuan.exists():
        return tujuan
    rng = np.random.default_rng(5)
    d = 128
    t = np.arange(d * SR) / SR
    kiri, kanan = np.zeros_like(t), np.zeros_like(t)
    akor = [(261.63, 329.63, 392.00), (196.00, 246.94, 293.66), (220.00, 261.63, 329.63), (174.61, 220.00, 261.63)]
    bass = [65.41, 98.00, 110.00, 87.31]
    panjang = 8.0
    for k in range(int(d / panjang)):
        a0, a1 = int(k * panjang * SR), int((k + 1) * panjang * SR)
        tt = t[a0:a1] - k * panjang
        env = np.minimum(1, tt / 1.5) * np.minimum(1, (panjang - tt) / 1.2)  # masuk & keluar pelan
        nada = akor[k % 4]
        for j, f in enumerate(nada):
            for detune, pan in ((0.997, 0.75), (1.003, 0.25)):  # dua lapis sedikit sumbang = pad yang lebar
                g = 0.07 * np.sin(2 * np.pi * f * detune * tt + j) * env
                kiri[a0:a1] += g * pan
                kanan[a0:a1] += g * (1 - pan)
        b = 0.10 * np.sin(2 * np.pi * bass[k % 4] * tt) * env * (0.75 + 0.25 * np.sin(2 * np.pi * tt / 2))
        kiri[a0:a1] += b
        kanan[a0:a1] += b
        # arpeggio: petikan tiap 0,5 detik naik-turun pada nada akor (satu oktaf di atas), sedikit acak volumenya
        urut = [nada[0], nada[1], nada[2], nada[1] * 2, nada[2], nada[1], nada[0] * 2, nada[1]]
        for m in range(int(panjang / 0.5)):
            i0 = a0 + int(m * 0.5 * SR)
            n = int(0.9 * SR)
            if i0 + n > len(t):
                break
            ts = np.arange(n) / SR
            f = urut[m % len(urut)] * 2
            petik = (np.sin(2 * np.pi * f * ts) + 0.3 * np.sin(4 * np.pi * f * ts)) * np.exp(-ts * 5.5)
            kuat = 0.05 * rng.uniform(0.7, 1.0)
            pan = 0.5 + 0.35 * np.sin(m * 0.9)
            kiri[i0:i0 + n] += petik * kuat * pan
            kanan[i0:i0 + n] += petik * kuat * (1 - pan)
    stereo = np.stack([_lowpass(kiri, 5000), _lowpass(kanan, 5000)], axis=1)
    stereo *= np.minimum(1, np.minimum(t / 2, (d - t) / 2))[:, None]  # ujung loop halus
    stereo = stereo / (np.abs(stereo).max() + 1e-9) * 0.6
    return _simpan(tujuan, stereo)


def _whoosh(durasi=0.7, rng=None):
    rng = rng or np.random.default_rng()
    n = int(durasi * SR)
    t = np.arange(n) / SR
    # tiga pita noise yang muncul bergantian → kesan "nada naik" lalu lewat
    hasil = np.zeros(n)
    for i, (b, a) in enumerate(((250, 900), (700, 2200), (1800, 5000))):
        pusat = durasi * (0.35 + 0.12 * i)
        env = np.exp(-((t - pusat) / (durasi * 0.22)) ** 2)
        hasil += _bandpass(rng.standard_normal(n), b, a) * env * (1.0 - 0.25 * i)
    hasil /= np.abs(hasil).max() + 1e-9
    geser = np.clip(t / durasi, 0, 1)  # bergerak dari kiri ke kanan
    return np.stack([hasil * (1 - geser * 0.7), hasil * (0.3 + geser * 0.7)], axis=1)


def _dentuman(durasi=1.6):
    n = int(durasi * SR)
    t = np.arange(n) / SR
    frek = 58 * np.exp(-t * 1.6) + 30  # nada turun
    fase = 2 * np.pi * np.cumsum(frek) / SR
    bass = np.sin(fase) * np.exp(-t * 2.6)
    hantam = _lowpass(np.random.default_rng(3).standard_normal(n), 900) * np.exp(-t * 18)
    hasil = bass + hantam / (np.abs(hantam).max() + 1e-9) * 0.5
    hasil /= np.abs(hasil).max() + 1e-9
    return np.stack([hasil, hasil], axis=1)


# ---------------------------------------------------------------- efek suara yang searah dengan isi adegan
# Semua dibuat sendiri dengan numpy (bebas hak cipta). Dulu hanya whoosh di tiap pergantian adegan + dentuman di
# awal: pengguna menilai "kurang variatif dan tidak searah dengan video".

def _mono(x):
    return np.stack([x, x], axis=1)


def _norm(x, puncak=1.0):
    return x / (np.abs(x).max() + 1e-9) * puncak


def _rana(rng):
    """Rana kamera: klik, desis mekanik, klik kedua."""
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    hasil = np.zeros(n)
    for mulai, kuat in ((0.0, 1.0), (0.09, 0.8)):
        i = int(mulai * SR)
        klik = _bandpass(rng.standard_normal(int(0.012 * SR)), 2500, 9000) * np.exp(-np.arange(int(0.012 * SR)) / SR * 400)
        hasil[i:i + len(klik)] += klik * kuat
    hasil += _bandpass(rng.standard_normal(n), 800, 3000) * np.exp(-((t - 0.05) / 0.03) ** 2) * 0.35
    return _mono(_norm(hasil))


def _glitch(rng, durasi=0.3):
    """Desis digital rusak: potongan gelombang kotak berfrekuensi acak + noise yang dikasarkan, berpindah kiri-kanan."""
    n = int(durasi * SR)
    hasil = np.zeros((n, 2))
    i = 0
    while i < n:
        panjang = int(rng.uniform(0.012, 0.035) * SR)
        f = rng.uniform(180, 2600)
        t = np.arange(panjang) / SR
        x = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.round(rng.standard_normal(panjang) * 3) / 6
        kiri = rng.uniform(0.2, 1.0)
        hasil[i:i + panjang] += np.stack([x * kiri, x * (1.2 - kiri)], axis=1)[: n - i]
        i += panjang + int(rng.uniform(0, 0.012) * SR)
    return _norm(hasil) * np.linspace(1, 0.4, n)[:, None]


def _hentakan(rng, durasi=0.9):
    """Hantaman pendek: bass turun + transien."""
    n = int(durasi * SR)
    t = np.arange(n) / SR
    frek = 75 * np.exp(-t * 3) + 38
    bass = np.sin(2 * np.pi * np.cumsum(frek) / SR) * np.exp(-t * 4.5)
    transien = _lowpass(rng.standard_normal(n), 2500) * np.exp(-t * 40)
    return _mono(_norm(bass + _norm(transien) * 0.6))


def _riser(rng, durasi=2.0):
    """Ketegangan naik menjelang twist: noise yang pitanya makin tinggi + nada naik, makin keras lalu putus."""
    n = int(durasi * SR)
    t = np.arange(n) / SR
    hasil = np.zeros(n)
    potong = 6
    for k in range(potong):  # pita noise yang bergeser naik
        a, b = int(k * n / potong), int((k + 1) * n / potong)
        pusat = 300 * (13 ** (k / (potong - 1)))
        hasil[a:b] += _bandpass(rng.standard_normal(b - a), pusat * 0.6, pusat * 1.6)
    nada = np.sin(2 * np.pi * np.cumsum(220 + 700 * (t / durasi) ** 2) / SR) * 0.4
    return _mono(_norm((_norm(hasil) + nada) * (t / durasi) ** 2.2))


def _pop(rng):
    """Bunyi "plop" stiker yang ditempel: nada naik cepat dengan peluruhan pendek + klik kecil di depannya."""
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    nada = np.sin(2 * np.pi * np.cumsum(280 + 900 * (1 - np.exp(-t * 60))) / SR) * np.exp(-t * 32)
    klik = _bandpass(rng.standard_normal(n), 2000, 7000) * np.exp(-t * 400) * 0.4
    return _mono(_norm(nada + klik))


def _swell(rng):
    """Whoosh terbalik: menarik masuk ke potongan berikutnya."""
    return _whoosh(0.8, rng)[::-1].copy()


# suasana latar (diputar pelan sepanjang adegan)
def _sua_angin(n, rng):
    lfo = _lowpass(rng.standard_normal(n), 0.4)
    return _lowpass(rng.standard_normal(n), 600) * (0.6 + 0.4 * _norm(lfo))


def _sua_air(n, rng):
    t = np.arange(n) / SR
    ombak = 0.55 + 0.45 * np.sin(2 * np.pi * t / 6.5 + rng.uniform(0, 6)) ** 2
    return _lowpass(rng.standard_normal(n), 1100) * ombak + _bandpass(rng.standard_normal(n), 2500, 6000) * ombak ** 3 * 0.3


def _sua_radio(n, rng):
    """Statis radio + bunyi "beep" Quindar khas komunikasi NASA (2525 Hz di awal, 2475 Hz di akhir)."""
    statis = _bandpass(rng.standard_normal(n), 400, 3200) * 0.5
    kresek = np.zeros(n)
    for i in rng.integers(0, n, max(1, n // SR * 6)):
        kresek[i:i + 300] += rng.standard_normal(min(300, n - i)) * 2
    hasil = statis + _bandpass(kresek, 800, 5000)
    for f, mulai in ((2525, 0.15), (2475, max(0.2, n / SR - 0.45))):
        i, m = int(mulai * SR), int(0.25 * SR)
        if i + m <= n:
            hasil[i:i + m] += np.sin(2 * np.pi * f * np.arange(m) / SR) * 1.2
    return hasil


def _sua_tetes(n, rng):
    """Tetesan air di gua: bunyi "tik" bernada turun dengan gema, di atas dengung rendah."""
    hasil = _lowpass(rng.standard_normal(n), 150) * 0.5
    t = 0.3
    while t < n / SR - 0.4:
        m = int(0.06 * SR)
        tt = np.arange(m) / SR
        tik = np.sin(2 * np.pi * np.cumsum(1800 * np.exp(-tt * 18)) / SR) * np.exp(-tt * 60)
        for jeda, kuat in ((0, 1), (0.12, 0.4), (0.27, 0.2)):
            i = int((t + jeda) * SR)
            if i + m <= n:
                hasil[i:i + m] += tik * kuat * 3
        t += rng.uniform(0.8, 2.0)
    return hasil


def _sua_ketik(n, rng):
    """Mesin ketik: rentetan klik, sesekali bunyi "ting" akhir baris."""
    hasil = np.zeros(n)
    t = 0.2
    while t < n / SR - 0.3:
        akhir = t + rng.uniform(0.8, 1.8)
        while t < min(akhir, n / SR - 0.3):
            i, m = int(t * SR), int(0.008 * SR)
            hasil[i:i + m] += _bandpass(rng.standard_normal(m), 1500, 6000) * np.exp(-np.arange(m) / SR * 500) * 3
            t += rng.uniform(0.09, 0.17)
        i, m = int(t * SR), int(0.4 * SR)
        if i + m <= n and rng.random() < 0.5:
            hasil[i:i + m] += np.sin(2 * np.pi * 2200 * np.arange(m) / SR) * np.exp(-np.arange(m) / SR * 9) * 0.8
        t += rng.uniform(0.6, 1.4)
    return hasil


def _sua_kertas(n, rng):
    hasil = np.zeros(n)
    t = 0.2
    while t < n / SR - 0.6:
        m = int(rng.uniform(0.25, 0.55) * SR)
        i = int(t * SR)
        env = np.abs(_lowpass(rng.standard_normal(m), 25))
        hasil[i:i + m] += _bandpass(rng.standard_normal(m), 2000, 8000) * _norm(env) * 1.5
        t += rng.uniform(1.0, 2.5)
    return hasil


def _sua_gemuruh(n, rng):
    lfo = 0.6 + 0.4 * _norm(_lowpass(rng.standard_normal(n), 0.3))
    return _lowpass(rng.standard_normal(n), 120) * lfo * 2


def _sua_malam(n, rng):
    """Jangkrik di malam hari + angin tipis."""
    hasil = _lowpass(rng.standard_normal(n), 500) * 0.3
    t = 0.1
    while t < n / SR - 0.2:
        for k in range(3):
            i, m = int((t + k * 0.033) * SR), int(0.015 * SR)
            if i + m <= n:
                hasil[i:i + m] += np.sin(2 * np.pi * 4600 * np.arange(m) / SR) * np.hanning(m) * 0.6
        t += rng.uniform(0.45, 0.8)
    return hasil


def _sua_detak(n, rng):
    """Detak jantung pelan (tegang)."""
    hasil = np.zeros(n)
    t = 0.2
    while t < n / SR - 0.4:
        for jeda, kuat in ((0, 1.0), (0.22, 0.7)):
            i, m = int((t + jeda) * SR), int(0.12 * SR)
            if i + m <= n:
                tt = np.arange(m) / SR
                hasil[i:i + m] += np.sin(2 * np.pi * 52 * tt) * np.exp(-tt * 28) * kuat * 3
        t += 0.92
    return hasil


_SUASANA = [  # urutan = prioritas
    ("radio", r"\b(nasa|apollo|astronot|roket|siaran|radio|antariksa|luar angkasa|satelit|orbit|houston|misi)\w*|"
              r"\b(di|ke|permukaan) bulan\b"),
    ("air", r"\b(laut|danau|sungai|ombak|loch|nessie|samudra|pantai|kapal|bawah air|perairan|teluk)\w*"),
    ("tetes", r"\b(gua|goa|terowongan|bawah tanah|makam|kuburan|lorong)\w*"),
    ("ketik", r"\b(dokumen|rahasia|arsip|laporan|surat|klasifikasi|cia|fbi|pemerintah|militer|perjanjian)\w*"),
    ("kertas", r"\b(buku|kitab|naskah kuno|manuskrip|peta|catatan kuno|prasasti)\w*"),
    ("gemuruh", r"\b(gempa|letusan|vulkan|batu|batuan|runtuh|megalit|piramida|tebing|membatu|fosil)\w*"),
    # tanpa "bulan" dan "angin": di Bulan tidak ada angin, dan "tanpa adanya angin" malah memicu suara angin
    ("angin", r"\b(gunung|kutub|antartika|gurun|badai|puncak|salju|padang|tundra)\w*|\bes\b"),
    ("malam", r"\b(malam|hutan|gelap|kegelapan)\w*"),
    ("detak", r"\b(takut|ngeri|hilang|lenyap|mati|tewas|menyerang|teror|korban)\w*"),
]
_PEMBUAT_SUASANA = {"angin": _sua_angin, "air": _sua_air, "radio": _sua_radio, "tetes": _sua_tetes,
                    "ketik": _sua_ketik, "kertas": _sua_kertas, "gemuruh": _sua_gemuruh, "malam": _sua_malam,
                    "detak": _sua_detak}
_KUAT_SUASANA = {"angin": 0.07, "air": 0.07, "radio": 0.05, "tetes": 0.09, "ketik": 0.06, "kertas": 0.06,
                 "gemuruh": 0.10, "malam": 0.06, "detak": 0.10}

TRANSISI = ("glitch", "whip", "kilat", "zoom", "terbakar", "gelap")
_TEGANG = r"\b(tapi|namun|anehnya|di sinilah|pertanyaannya|bayangkan|ternyata|justru|lebih aneh)\b"
_TWIST = r"\b(mungkin saja|ada yang menduga|faktanya|jawabannya|kebenarannya)\b"
_FOTO = r"\b(foto|kamera|potret|difoto|rekaman|gambar ini)\b"
_SERAM = r"\b(takut|ngeri|hilang|lenyap|menyerang|teror|tewas|korban)\w*"


_SUASANA_CERAH = {"air", "angin", "radio", "gemuruh", "malam"}  # video sains: tanpa detak jantung/ketik/tetes gua


def rencana(adegan, gaya="misterius"):
    """Efek tiap adegan dari isinya: transisi gambar, gerak kamera shot pertama, suasana latar, dan aksen suara.
    Transisi biasa bergiliran supaya tidak monoton; adegan penting mendapat transisi & aksen khusus.
    gaya="cerah" (video sains): transisi halus saja dan suasana alam, tanpa bunyi menegangkan."""
    cerah = gaya == "cerah"
    giliran = ["whip", "gelap", "kilat", "whip", "gelap"] if cerah else ["whip", "terbakar", "glitch", "gelap", "kilat"]
    hasil, lalu, k = [], None, 0
    for i, a in enumerate(adegan):
        q = a.get("q") or {}
        teks = f"{a.get('teks', '')} {q.get('lihat', '')} {q.get('subjek', '')}".lower()
        twist, tegang = re.search(_TWIST, teks), re.search(_TEGANG, teks)
        foto, seram = re.search(_FOTO, teks), re.search(_SERAM, teks)
        if i == 0:
            transisi = None
        elif twist:
            transisi = "zoom"
        elif foto:
            transisi = "kilat"
        elif tegang:
            transisi = "whip" if cerah else "glitch"
        else:
            transisi = giliran[k % len(giliran)]
            if transisi == lalu:
                k += 1
                transisi = giliran[k % len(giliran)]
            k += 1
        aksen = []
        if twist and i > 0:
            aksen.append("riser")
        if (tegang or a.get("teks", "").strip().endswith("?")) and transisi != "zoom":
            aksen.append("hentak")
        if foto:
            aksen.append("rana")
        suasana = next((nama for nama, pola in _SUASANA if re.search(pola, teks)
                        and (not cerah or nama in _SUASANA_CERAH)), None)
        gerak = "hentak" if (twist or tegang) else "goyang" if seram and not cerah else None
        hasil.append({"transisi": transisi, "aksen": aksen, "suasana": suasana, "gerak": gerak})
        lalu = transisi
    return hasil


def jalur_sfx(adegan, total, tujuan, banding=(), stiker=()):
    """Satu jalur WAV sepanjang video. adegan = [{mulai, durasi, transisi, aksen, suasana}] (lihat rencana()),
    banding = detik munculnya tulisan "MIRIP?" di perbandingan 🆚 (diberi hentakan), stiker = detik munculnya
    stiker foto (diberi bunyi "plop")."""
    rng = np.random.default_rng(11)
    jalur = np.zeros((int((total + 1) * SR), 2))

    def taruh(suara, detik, kuat):
        i0 = max(0, int(detik * SR))
        i1 = min(len(jalur), i0 + len(suara))
        if i1 > i0:
            jalur[i0:i1] += suara[:i1 - i0] * kuat

    taruh(_dentuman(), 0.05, 0.9)
    # suasana latar: adegan berurutan dengan suasana sama digabung jadi satu bentang, masuk-keluar pelan
    i = 0
    while i < len(adegan):
        nama = adegan[i].get("suasana")
        j = i
        while j + 1 < len(adegan) and adegan[j + 1].get("suasana") == nama:
            j += 1
        if nama in _PEMBUAT_SUASANA:
            mulai = adegan[i]["mulai"]
            lama = adegan[j]["mulai"] + adegan[j]["durasi"] - mulai
            n = int(lama * SR)
            if n > SR // 2:
                x = _norm(_PEMBUAT_SUASANA[nama](n, rng))
                pudar = min(int(0.5 * SR), n // 3)
                env = np.ones(n)
                env[:pudar], env[-pudar:] = np.linspace(0, 1, pudar), np.linspace(1, 0, pudar)
                taruh(_mono(x * env), mulai, _KUAT_SUASANA[nama])
        i = j + 1
    # transisi & aksen
    suara_transisi = {"glitch": (lambda: _glitch(rng), -0.05, 0.45), "whip": (lambda: _whoosh(0.7, rng), -0.32, 0.4),
                      "kilat": (lambda: _rana(rng), -0.02, 0.5), "zoom": (lambda: _swell(rng), -0.8, 0.45),
                      "terbakar": (lambda: _whoosh(0.9, rng), -0.45, 0.35), "gelap": (lambda: _dentuman(1.2), 0.0, 0.5)}
    for a in adegan:
        t = a.get("transisi")
        if t in suara_transisi:
            buat, geser, kuat = suara_transisi[t]
            taruh(buat(), a["mulai"] + geser, kuat)
            if t == "zoom":
                taruh(_hentakan(rng), a["mulai"], 0.6)
        if "riser" in a.get("aksen", []):
            r = _riser(rng)
            taruh(r, a["mulai"] - len(r) / SR, 0.35)
        if "hentak" in a.get("aksen", []):
            taruh(_hentakan(rng), a["mulai"] + 0.02, 0.45)
        if "rana" in a.get("aksen", []) and t != "kilat":
            taruh(_rana(rng), a["mulai"] + 0.15, 0.45)
    for detik in banding:
        taruh(_hentakan(rng), detik, 0.6)
    for detik in stiker:
        taruh(_pop(rng), detik + 0.03, 0.35)
    return _simpan(tujuan, np.clip(jalur[: int(total * SR)], -1, 1))
