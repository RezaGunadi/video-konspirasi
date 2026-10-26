"""Narasi suara dengan Microsoft Edge TTS (gratis, perlu internet) + waktu tiap kata untuk subtitle."""
import asyncio
import difflib
import json
import os
import re
import time
from pathlib import Path

import edge_tts

from .alat import CACHE, Dibatalkan, hash_pendek, probe

SUARA = {
    "id-ID-ArdiNeural": "Ardi (pria, Indonesia)",
    "id-ID-GadisNeural": "Gadis (wanita, Indonesia)",
    # Suara "Multilingual" generasi baru: intonasinya lebih ekspresif seperti orang ngobrol dan bisa membaca bahasa
    # Indonesia (Whisper mengenali 91-95% kata, setara Ardi), kadang dengan sedikit logat.
    "en-US-AndrewMultilingualNeural": "Andrew (pria, hangat, multibahasa)",
    "en-US-BrianMultilingualNeural": "Brian (pria, santai, multibahasa)",
    "en-US-AvaMultilingualNeural": "Ava (wanita, ekspresif, multibahasa)",
    "en-US-EmmaMultilingualNeural": "Emma (wanita, ceria, multibahasa)",
}

FOLDER = CACHE / "suara"
FOLDER.mkdir(parents=True, exist_ok=True)


async def _tts(teks, suara, rate, pitch, mp3):
    c = edge_tts.Communicate(teks, suara, rate=rate, pitch=pitch, boundary="WordBoundary")
    kata = []
    with open(mp3, "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                t0 = ch["offset"] / 1e7
                kata.append({"t0": round(t0, 3), "t1": round(t0 + ch["duration"] / 1e7, 3), "teks": ch["text"]})
    return kata


_whisper = None


def _model_whisper():
    global _whisper
    if _whisper is None:
        from .alat import HF_CACHE
        os.environ.setdefault("HF_HOME", str(HF_CACHE))
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8",
                                download_root=str(HF_CACHE / "whisper"))
    return _whisper


def _token(t):
    return re.findall(r"\w+", t.lower())


def _energi(mp3):
    """Kekerasan suara per 10 ms (RMS) + ambang 'ada suara'."""
    import numpy as np
    from .alat import FFMPEG, NO_WINDOW
    import subprocess
    pcm = subprocess.run([FFMPEG, "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, creationflags=NO_WINDOW).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 160
    rms = np.sqrt((x[: n * 160].reshape(n, 160) ** 2).mean(axis=1) + 1e-12)
    aktif = rms[rms > np.percentile(rms, 30)]
    ambang = max(0.006, float(np.median(aktif)) * 0.12) if len(aktif) else 0.01
    return rms, ambang


def _rapatkan_ke_suara(kata, mp3):
    """Whisper suka menaruh awal kata pertama setelah jeda terlalu awal (ikut menelan hening). Kalau di awal
    kata masih hening, geser awalnya ke saat suara benar-benar terdengar."""
    try:
        rms, ambang = _energi(mp3)
    except Exception:
        return kata
    for k in kata:
        a, b = int(k["t0"] * 100), min(int(k["t1"] * 100), len(rms))
        if b <= a:
            continue
        akhir_hening, run = None, 0
        for i in range(a, b):  # cari hening ≥150 ms di dalam rentang kata (bisa diawali sisa kata sebelumnya)
            if rms[i] <= ambang:
                run += 1
            else:
                if run >= 15:
                    akhir_hening = i
                run = 0
        if akhir_hening is not None and akhir_hening < b - 5:
            k["t0"] = round(akhir_hening / 100 - 0.02, 3)
    return kata


def _pecah_frasa(kata):
    """Edge kadang mengirim satu "kata" berisi frasa angka ("500 hingga 200"); pecah per kata supaya subtitle
    menyorot "500" → "HINGGA" → "200" berurutan, bukan menampilkan "200" sebelum diucapkan."""
    hasil = []
    for k in kata:
        bagian = k["teks"].split()
        if len(bagian) <= 1:
            hasil.append(k)
            continue
        panjang = [max(1, len(b)) for b in bagian]
        t = k["t0"]
        for b, n in zip(bagian, panjang):
            d = (k["t1"] - k["t0"]) * n / sum(panjang)
            hasil.append({"t0": round(t, 3), "t1": round(t + d, 3), "teks": b})
            t += d
    return hasil


def selaraskan(mp3, kata, log=print, batal=None):
    """Waktu kata dari Edge TTS meleset 0,4–1,1 detik di sekitar angka ("9.000 hingga 20.000" dibaca
    "sembilan ribu hingga dua puluh ribu") dan kata ulang. Whisper mendengarkan narasinya; kata yang cocok
    memakai waktu dari Whisper, kata yang tidak cocok (angka dll.) diletakkan di celah di antaranya.
    Teks tetap dari Edge/naskah. Hasil disimpan di cache di samping mp3."""
    kata = _pecah_frasa(kata)
    cache = Path(mp3).with_suffix(".whisper.json")
    if cache.exists():
        dengar = json.loads(cache.read_text(encoding="utf-8"))
    else:
        try:
            segmen, _ = _model_whisper().transcribe(str(mp3), language="id", word_timestamps=True, beam_size=5,
                                                     vad_filter=False)
            dengar = []
            for s in segmen:  # generator: tiap segmen bisa disela tombol Batal / Tulis ulang
                if batal:
                    batal.cek()
                dengar += [[w.word, round(w.start, 3), round(w.end, 3)] for w in s.words]
        except Dibatalkan:
            raise
        except Exception as e:  # Whisper tidak tersedia: pakai waktu Edge apa adanya
            log(f"Penyelarasan Whisper gagal ({e}); pakai waktu dari Edge TTS")
            return kata, False
        cache.write_text(json.dumps(dengar, ensure_ascii=False), encoding="utf-8")
    e_tok, e_idx = [], []
    for i, k in enumerate(kata):
        for t in _token(k["teks"]):
            e_tok.append(t)
            e_idx.append(i)
    d_tok, d_waktu = [], []
    for w, t0, t1 in dengar:
        for t in _token(w):
            d_tok.append(t)
            d_waktu.append((t0, t1))
    waktu = [None] * len(kata)
    for blok in difflib.SequenceMatcher(a=e_tok, b=d_tok, autojunk=False).get_matching_blocks():
        for d in range(blok.size):
            i = e_idx[blok.a + d]
            t0, t1 = d_waktu[blok.b + d]
            waktu[i] = (t0, t1) if waktu[i] is None else (min(waktu[i][0], t0), max(waktu[i][1], t1))
    cocok = sum(1 for w in waktu if w)
    if cocok < len(kata) * 0.6:  # transkrip terlalu beda: lebih aman pakai waktu Edge
        log(f"Whisper hanya cocok {cocok}/{len(kata)} kata; pakai waktu dari Edge TTS")
        return kata, False
    # Kata yang tidak cocok (angka, kata yang Whisper gabung/pisah lain): pakai waktu Edge-nya sendiri, digeser
    # sebesar selisih Edge→Whisper di tetangga terdekat yang cocok. Membagi rata celah antar-tetangga salah
    # kalau di celah itu ada jeda paragraf (kata jadi jatuh di dalam hening).
    cocok_idx = [i for i, w in enumerate(waktu) if w]
    hasil = [dict(k) for k in kata]
    for i, k in enumerate(kata):
        if waktu[i]:
            hasil[i]["t0"], hasil[i]["t1"] = waktu[i]
            continue
        sebelum = max((c for c in cocok_idx if c < i), default=None)
        sesudah = min((c for c in cocok_idx if c > i), default=None)
        geser = [waktu[c][0] - kata[c]["t0"] for c in (sebelum, sesudah) if c is not None]
        g = sum(geser) / len(geser) if geser else 0.0
        bawah = hasil[sebelum]["t1"] if sebelum is not None else 0.0
        atas = waktu[sesudah][0] if sesudah is not None else k["t1"] + g + 5
        t0 = min(max(k["t0"] + g, bawah), atas - 0.05)
        t1 = min(max(k["t1"] + g, t0 + 0.08), atas)
        hasil[i]["t0"], hasil[i]["t1"] = round(t0, 3), round(t1, 3)
    for x, y in zip(hasil, hasil[1:]):  # jaga urutan
        if y["t0"] < x["t0"]:
            y["t0"] = x["t0"]
        y["t1"] = max(y["t1"], y["t0"] + 0.05)
    hasil = _rapatkan_ke_suara(hasil, mp3)
    log(f"Waktu subtitle diselaraskan dengan suara (Whisper cocok {cocok}/{len(kata)} kata)")
    return hasil, True


async def _tts_jaga(teks, suara, rate, pitch, mp3, batas, batal=None):
    """Edge TTS dengan batas waktu dan bisa dibatalkan. Tanpa ini koneksi ke Microsoft yang menggantung membuat
    proses diam selamanya (antrean pernah macet ±34 jam di "Membacakan naskah")."""
    tugas = asyncio.ensure_future(_tts(teks, suara, rate, pitch, mp3))
    mulai = time.monotonic()
    try:
        while True:
            selesai, _ = await asyncio.wait({tugas}, timeout=1)
            if selesai:
                return tugas.result()
            if batal:
                batal.cek()
            if time.monotonic() - mulai > batas:
                raise TimeoutError(f"Edge TTS tidak selesai dalam {int(batas)} detik")
    finally:
        if not tugas.done():
            tugas.cancel()
            try:
                await tugas
            except BaseException:
                pass


def bacakan(teks, suara, kecepatan, nada, batal=None):
    """Mengembalikan {mp3, durasi, kata}; hasil disimpan di cache supaya render ulang tidak memanggil TTS lagi."""
    rate = f"{int(kecepatan):+d}%"
    pitch = f"{int(nada):+d}Hz"
    kunci = hash_pendek(json.dumps([teks, suara, rate, pitch]))
    mp3, meta = FOLDER / f"{kunci}.mp3", FOLDER / f"{kunci}.json"
    if mp3.exists() and meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    galat = None
    for coba in range(4):
        if batal:
            batal.cek()
        try:
            # ±563 kata biasanya selesai 45 detik; batas longgar supaya naskah 20 menit tetap muat
            batas = 120 + len(teks.split()) * 0.6
            kata = asyncio.run(_tts_jaga(teks, suara, rate, pitch, mp3, batas, batal))
            if mp3.stat().st_size < 1000:
                raise RuntimeError("audio kosong")
            hasil = {"mp3": str(mp3), "durasi": probe(mp3)["durasi"], "kata": kata}
            meta.write_text(json.dumps(hasil, ensure_ascii=False), encoding="utf-8")
            return hasil
        except Dibatalkan:
            mp3.unlink(missing_ok=True)
            raise
        except Exception as e:  # jaringan/limit Microsoft/menggantung: tunggu lalu coba lagi
            galat = e
            mp3.unlink(missing_ok=True)
            time.sleep(3 + coba * 4)
    raise RuntimeError(f"Edge TTS gagal (cek internet): {galat}")


# ---------------------------------------------------------------- suara lebih manusiawi

_BALIK = {"tapi", "namun", "ternyata", "padahal", "faktanya", "justru", "bahkan", "anehnya", "masalahnya", "nah"}
JEDA_AWAL = 0.35  # detik hening sebelum kata pertama narasi
# Rantai "mikrofon": potong dengung rendah, sedikit hangat, presence, de-esser, kompresi halus, dan gema ruangan
# kecil — TTS yang kering terdengar seperti suara sintetis; sedikit ruang membuatnya terdengar seperti rekaman.
_RANTAI = ("highpass=f=70,bass=g=1.5:f=160:w=0.7,equalizer=f=3200:t=q:w=1.0:g=1.2,deesser=i=0.3,"
           "acompressor=threshold=-21dB:ratio=2.2:attack=10:release=160:makeup=1.6,"
           "aecho=0.88:0.9:17|29|43:0.06|0.045|0.03,aresample=48000")


def _batas_kalimat(naskah, kata):
    """Tanda baca/paragraf SETELAH tiap kata TTS (Edge mengirim kata tanpa tanda baca): dicocokkan ke naskah."""
    tok, tanda = [], []
    for par_i, par in enumerate(re.split(r"\n\s*\n", naskah)):
        bagian = re.findall(r"(\w[\w'-]*)([^\w\s]*)", par)
        for j, (w, p) in enumerate(bagian):
            for t in _token(w):
                tok.append(t)
                tanda.append("")
            tanda[-1] = ("¶" if j == len(bagian) - 1 and par_i >= 0 else "") + p
    k_tok, k_idx = [], []
    for i, k in enumerate(kata):
        for t in _token(k["teks"]):
            k_tok.append(t)
            k_idx.append(i)
    hasil = [""] * len(kata)
    for blok in difflib.SequenceMatcher(a=tok, b=k_tok, autojunk=False).get_matching_blocks():
        for d in range(blok.size):
            hasil[k_idx[blok.b + d]] = tanda[blok.a + d]
    return hasil


def _jeda_target(tanda, kalimat_ini, kata_berikut, acak):
    """Panjang jeda (detik) yang diinginkan setelah sebuah kalimat, seperti narator manusia: paragraf baru lebih
    lama, pertanyaan dibiarkan "mendarat", kalimat sebelum "Tapi…/Ternyata…" diberi jeda dramatis, kalimat
    sangat pendek ("Bukan kiasan.") diberi ruang. None = koma/tengah kalimat, jangan diubah."""
    if "¶" in tanda:
        dasar = 0.85
    elif "?" in tanda:
        dasar = 0.72
    elif "…" in tanda or "..." in tanda or ":" in tanda:
        dasar = 0.6
    elif "." in tanda or "!" in tanda:
        dasar = 0.5
    else:
        return None
    if kata_berikut in _BALIK:
        dasar += 0.15
    if kalimat_ini <= 4:
        dasar += 0.08
    return dasar + acak.uniform(-0.07, 0.07)


def manusiawikan(mp3, kata, naskah, batal=None):
    """Narasi Edge TTS dibuat lebih manusiawi: jeda antarkalimat bervariasi sesuai isi (bukan jeda seragam
    mesin) dan diberi warna rekaman (rantai mikrofon + ruang kecil). Waktu kata ikut digeser supaya subtitle tetap
    pas. Mengembalikan (wav, kata_baru); hasil di-cache."""
    import random
    import subprocess
    import numpy as np
    import soundfile as sf
    from .alat import FFMPEG, NO_WINDOW
    kunci = hash_pendek(json.dumps([str(mp3), Path(mp3).stat().st_size, naskah, _RANTAI, 3]))
    wav, meta = FOLDER / f"{kunci}-alami.wav", FOLDER / f"{kunci}-alami.json"
    if wav.exists() and meta.exists():
        return str(wav), json.loads(meta.read_text(encoding="utf-8"))
    sr = 24000
    pcm = subprocess.run([FFMPEG, "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, creationflags=NO_WINDOW, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    win = sr // 100
    n = len(x) // win
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
    ambang = max(0.004, float(np.median(rms[rms > np.percentile(rms, 30)])) * 0.08)
    tanda = _batas_kalimat(naskah, kata)
    acak = random.Random(kunci)
    # Jeda singkat sebelum kata pertama: tanpa ini kata pertama bertabrakan dengan dentuman pembuka & fade-in video
    # dan terdengar "terpotong" di awal naskah.
    awal = np.zeros(int(JEDA_AWAL * sr), np.float32)
    potongan, geser, kursor, panjang_kalimat = [awal], [(-1.0, JEDA_AWAL)], 0, 0  # geser: (detik_asal, selisih)
    for i in range(len(kata) - 1):
        if batal and i % 200 == 0:
            batal.cek()
        panjang_kalimat += 1
        target = _jeda_target(tanda[i], panjang_kalimat, (_token(kata[i + 1]["teks"]) or [""])[0], acak)
        if target is None:
            continue
        panjang_kalimat = 0
        # rentang hening yang sebenarnya di sekitar celah kata (waktu Whisper/Edge bisa meleset ±50 ms)
        a = max(0, int((kata[i]["t1"] - 0.05) * 100))
        b = min(n, int((kata[i + 1]["t0"] + 0.05) * 100))
        if b - a < 8:
            continue
        sunyi = rms[a:b] <= ambang
        if not sunyi.any():
            continue
        # run hening terpanjang
        terbaik, mulai_run, s0, s1 = 0, None, 0, 0
        for j, v in enumerate(list(sunyi) + [False]):
            if v and mulai_run is None:
                mulai_run = j
            elif not v and mulai_run is not None:
                if j - mulai_run > terbaik:
                    terbaik, s0, s1 = j - mulai_run, mulai_run, j
                mulai_run = None
        if terbaik < 12:  # < 120 ms: bukan jeda kalimat yang jelas
            continue
        lama = terbaik / 100
        baru = min(max(target, 0.25), lama + 0.5)
        selisih = baru - lama
        if abs(selisih) < 0.04:
            continue
        tengah = int((a + (s0 + s1) / 2) * win)  # sampel di tengah hening
        if selisih > 0:
            potongan += [x[kursor:tengah], np.zeros(int(selisih * sr), np.float32)]
            kursor = tengah
        else:
            # Dipotong SIMETRIS di tengah hening (sisa ≥125 ms di kiri & kanan). Dulu dipotong dari tengah ke kanan
            # sepanjang selisihnya: jeda Ardi ±1,1 detik yang dipendekkan ke ±0,4 detik ikut memakan 0,05-0,2 detik
            # awal kata berikutnya, sehingga awal kalimat/paragraf terdengar terpotong atau melompat.
            setengah = int(-selisih * sr / 2)
            potongan.append(x[kursor:tengah - setengah])
            kursor = tengah + setengah
        geser.append((tengah / sr, selisih))
    potongan.append(x[kursor:])
    y = np.concatenate(potongan) if potongan else x
    mentah = FOLDER / f"{kunci}-jeda.wav"
    sf.write(str(mentah), y, sr)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(mentah), "-af", _RANTAI, "-ac", "1", str(wav)],
                   creationflags=NO_WINDOW, check=True)
    mentah.unlink(missing_ok=True)

    def pindah(t):
        return round(t + sum(d for t0, d in geser if t0 < t), 3)

    kata_baru = [{**k, "t0": pindah(k["t0"]), "t1": pindah(k["t1"])} for k in kata]
    meta.write_text(json.dumps(kata_baru, ensure_ascii=False), encoding="utf-8")
    return str(wav), kata_baru
