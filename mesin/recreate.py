"""Mode Re-create: beberapa video pendek dari SATU video panjang (proyek aplikasi ini atau file video milik pengguna).

Naskah tiap short ditulis ulang dari transkrip sumber sesuai tema, suaranya dibacakan ulang dengan suara yang
disamakan dengan sumber, dan visualnya diambil dari bagian sumber yang membahas hal yang sama.
"""
import json
import os
import re
import subprocess

from .alat import CACHE, FFMPEG, hash_pendek, probe

FOLDER = CACHE / "recreate"
_UMUM = {"yang", "dan", "di", "ke", "dari", "ini", "itu", "dengan", "untuk", "pada", "adalah", "dalam", "tidak",
         "akan", "atau", "juga", "karena", "bahwa", "para", "sebagai", "lebih", "sudah", "bisa", "ada", "kita",
         "kamu", "mereka", "namun", "tapi", "bahkan", "seperti", "hanya", "saja", "masih", "telah", "sangat",
         "banyak", "semua", "menjadi", "sebuah", "hingga", "tetapi", "jika", "kalau", "apakah", "bagaimana"}


def _kunci_file(path):
    st = os.stat(path)
    return hash_pendek(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}")


# ---------------------------------------------------------------- transkrip

def transkrip_proyek(src):
    """Proyek aplikasi ini: adegan sudah punya teks dan waktunya, tidak perlu Whisper."""
    return [{"t0": round(a.get("mulai", 0), 2), "t1": round(a.get("mulai", 0) + a.get("durasi", 0), 2),
             "teks": a["teks"], "adegan": i} for i, a in enumerate(src.get("adegan") or [])]


def transkrip_file(path, log=print, batal=None):
    """Whisper (model yang sama dengan penyelarasan subtitle) atas audio video sumber. Hasil di-cache."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    cache = FOLDER / f"transkrip-{_kunci_file(path)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    from .suara import _model_whisper
    log("Mentranskrip video sumber dengan Whisper (sekali saja, ±1x durasi video)…")
    segmen, info = _model_whisper().transcribe(str(path), language="id", beam_size=5, vad_filter=True)
    hasil = []
    for s in segmen:
        if batal:
            batal.cek()
        teks = " ".join(s.text.split())
        if teks:
            hasil.append({"t0": round(s.start, 2), "t1": round(s.end, 2), "teks": teks})
    cache.write_text(json.dumps(hasil, ensure_ascii=False), encoding="utf-8")
    log(f"Transkrip: {len(hasil)} bagian, {sum(len(h['teks'].split()) for h in hasil)} kata")
    return hasil


def teks_transkrip(transkrip, maks=12000):
    return "\n".join(t["teks"] for t in transkrip)[:maks]


# ---------------------------------------------------------------- suara sumber

def _audio_wav(path):
    """Audio video sumber sebagai WAV mono 16 kHz (librosa tidak bisa membaca mp4 langsung di sini)."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    tujuan = FOLDER / f"audio-{_kunci_file(path)}.wav"
    if not tujuan.exists():
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                        str(tujuan)], check=True, timeout=1800)
    return tujuan


def analisa_suara(path, transkrip):
    """Perkiraan suara pembicara sumber: pria/wanita (nada dasar), tinggi nada, dan kecepatan bicara.
    Dipakai untuk memilih suara Edge yang paling dekat (dan sebagai titik awal penyamaan warna suara)."""
    import numpy as np
    import librosa
    potong = [t for t in transkrip if t["t1"] - t["t0"] >= 2][:12]
    wav = _audio_wav(path)
    nada, kata, detik = [], 0, 0.0
    for t in potong:
        y, sr = librosa.load(str(wav), sr=16000, offset=t["t0"], duration=min(8.0, t["t1"] - t["t0"]))
        if len(y) < sr:
            continue
        f0 = librosa.yin(y, fmin=70, fmax=350, sr=sr)
        energi = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        n = min(len(f0), len(energi))
        f0 = f0[:n][energi[:n] > np.median(energi[:n])]  # hanya bagian bersuara
        nada += list(f0[(f0 > 75) & (f0 < 340)])
        kata += len(t["teks"].split())
        detik += t["t1"] - t["t0"]
    f0 = float(np.median(nada)) if nada else 0.0
    wps = kata / detik if detik else 2.3
    wanita = f0 >= 165
    dasar = 233.0 if wanita else 118.5  # nada dasar Gadis / Ardi tanpa geser (diukur dari Edge TTS)
    return {"f0": round(f0, 1), "kata_per_detik": round(wps, 2), "wanita": wanita,
            "suara": "id-ID-GadisNeural" if wanita else "id-ID-ArdiNeural",
            "nada": int(max(-20, min(20, round(f0 - dasar)))) if f0 else 0,
            "kecepatan": int(max(-25, min(25, round((wps / 2.35 - 1) * 100))))}


def referensi_suara(path, transkrip, maks=6):
    """Potongan ±8 detik bagian bicara dari video sumber (untuk sidik warna suara)."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    kunci = _kunci_file(path)
    hasil = []
    for t in sorted(transkrip, key=lambda t: -(t["t1"] - t["t0"]))[:maks]:
        tujuan = FOLDER / f"ref-{kunci}-{int(t['t0'] * 10)}.wav"
        if not tujuan.exists():
            subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t['t0']:.2f}", "-t",
                            f"{min(8.0, t['t1'] - t['t0']):.2f}", "-i", str(path), "-vn", "-ac", "1", "-ar", "22050",
                            str(tujuan)], check=True, timeout=120)
        hasil.append(str(tujuan))
    return hasil


# ---------------------------------------------------------------- pencocokan adegan ↔ sumber

def _kata(teks):
    return {k[:5] for k in re.findall(r"\w+", teks.lower()) if len(k) > 3 and k not in _UMUM}


def cocokkan(teks_adegan, transkrip, jendela=2):
    """Bagian transkrip sumber yang paling membahas hal yang sama dengan adegan baru (awalan 5 huruf kata penting;
    nama dan angka diberi bobot lebih). Mengembalikan (indeks_mulai, indeks_akhir, skor) atau None."""
    kata = _kata(teks_adegan)
    nama = {k[:5].lower() for k in re.findall(r"\b[A-Z][\w-]{3,}|\d{2,}", teks_adegan)}
    if not kata or not transkrip:
        return None
    terbaik = None
    for i in range(len(transkrip)):
        teks = " ".join(t["teks"] for t in transkrip[i:i + jendela])
        isi = _kata(teks)
        skor = len(kata & isi) + 1.5 * len(nama & isi)
        if not terbaik or skor > terbaik[2]:
            terbaik = (i, min(len(transkrip), i + jendela) - 1, skor)
    return terbaik if terbaik and terbaik[2] >= 2.5 else None


def klip_sumber(path, transkrip, cocok, nama):
    """Kandidat footage berupa potongan video sumber (dipakai apa adanya, tanpa unduh)."""
    info = probe(path)
    i0, i1, skor = cocok
    t0, t1 = transkrip[i0]["t0"], transkrip[i1]["t1"]
    if info.get("durasi", 0) > 30:
        t0 = max(t0, 3.0)  # 3 detik pertama video biasanya berisi judul/logo yang tertanam
    return {"id": f"sumber-{_kunci_file(path)}-{int(t0 * 10)}", "sumber": "Video sumber", "jenis": "video",
            "file": str(path), "mulai": t0, "durasi": round(t1 - t0, 2), "lebar": info["lebar"],
            "tinggi": info["tinggi"], "skor_ai": 9, "isi_ai": "bagian video sumber yang membahas hal ini",
            "judul": f"{nama} ({int(t0 // 60)}:{int(t0 % 60):02d})", "lisensi": "milik pengguna", "pembuat": "",
            "halaman": "", "teks": " ".join(t["teks"] for t in transkrip[i0:i1 + 1])[:200]}
