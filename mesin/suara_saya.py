"""Narasi dengan suara pengguna sendiri ("Suara saya").

Edge TTS (Ardi/Gadis, nadanya digeser mendekati nada bicara pengguna) membacakan naskah, lalu warna suaranya diubah
dengan OpenVoice V2 (suara_mirip) memakai potongan rekaman pengguna sebagai referensi. Intonasi dan tempo tetap dari
Edge, warna suaranya dari pengguna. Hanya untuk suara milik pengguna sendiri (profil dibuat dari channel miliknya).

Profil di data/suara-saya/: ref-*.wav (potongan bicara yang paling bersih) + profil.json.
"""
import json
import subprocess
from pathlib import Path

from . import suara_mirip
from .alat import DATA, FFMPEG, baca_json, hash_pendek, tulis_json

KODE = "saya"  # nilai opsi "suara"
LABEL = "🎙️ Suara saya (klon dari rekaman channel)"
FOLDER = DATA / "suara-saya"
PROFIL = FOLDER / "profil.json"
_NADA_ARDI, _NADA_GADIS = 118.5, 233.0  # nada dasar Edge tanpa geser (diukur, lihat recreate.analisa_suara)


def profil():
    return baca_json(PROFIL, {}) or {}


def referensi():
    return sorted(str(p) for p in FOLDER.glob("ref-*.wav"))


def ada():
    return PROFIL.exists() and bool(referensi()) and suara_mirip.tersedia()


def suara_dasar():
    return profil().get("suara_dasar", "id-ID-ArdiNeural")


def nada_dasar():
    return int(profil().get("nada", 0))


def ubah(audio):
    """Warna suara `audio` diubah jadi suara pengguna. Durasi tidak berubah (waktu kata/subtitle tetap pas).
    Hasil di-cache per isi file dan set referensinya."""
    refs, tau = referensi(), float(profil().get("tau", 0.3))
    kunci = hash_pendek(json.dumps([str(audio), Path(audio).stat().st_size, refs, tau]))
    tujuan = suara_mirip.FOLDER / f"saya-{kunci}.wav"
    if not tujuan.exists():
        suara_mirip.FOLDER.mkdir(parents=True, exist_ok=True)
        suara_mirip.samakan(audio, refs, tujuan, tau=tau)
    return str(tujuan)


def buat_profil(potongan, sumber="", maks=24):
    """potongan = [(file_audio, t0, t1)] bagian bicara PENGGUNA (sudah dipastikan suaranya, bukan anggota keluarga
    lain). Yang latarnya paling sunyi (sedikit musik/keramaian) disimpan sebagai referensi; nada median menentukan
    suara dasar Edge (Ardi/Gadis) dan geser nadanya supaya intonasi hasil klon dekat dengan aslinya."""
    import librosa
    import numpy as np
    calon = []
    for f, t0, t1 in potongan:
        y, sr = librosa.load(str(f), sr=16000, offset=t0, duration=t1 - t0)
        if len(y) < 2 * sr:
            continue
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        bersih = float(np.percentile(rms, 90) / (np.percentile(rms, 10) + 1e-6))  # tinggi = jeda kata sunyi
        f0 = librosa.yin(y, fmin=70, fmax=400, sr=sr, frame_length=2048, hop_length=512)
        n = min(len(f0), len(rms))
        f0 = f0[:n][rms[:n] > np.median(rms[:n])]
        f0 = f0[(f0 > 75) & (f0 < 390)]
        if len(f0) >= 10:
            calon.append((bersih, str(f), t0, t1, float(np.median(f0))))
    if len(calon) < 4:
        raise RuntimeError("Potongan suara terlalu sedikit untuk membuat profil (minimal 4 potongan ≥2 detik)")
    calon.sort(key=lambda c: -c[0])
    pilih = calon[:maks]
    FOLDER.mkdir(parents=True, exist_ok=True)
    for lama in FOLDER.glob("ref-*.wav"):
        lama.unlink()
    for i, (_, f, t0, t1, _) in enumerate(pilih):
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}", "-i", f,
                        "-ac", "1", "-ar", "22050", str(FOLDER / f"ref-{i:02d}.wav")], check=True, timeout=120)
    f0 = float(np.median([c[4] for c in pilih]))
    wanita = f0 >= 165
    tulis_json(PROFIL, {"sumber": sumber, "jumlah_ref": len(pilih), "detik": round(sum(c[3] - c[2] for c in pilih)),
                        "f0": round(f0, 1), "wanita": wanita,
                        "suara_dasar": "id-ID-GadisNeural" if wanita else "id-ID-ArdiNeural",
                        "nada": int(max(-20, min(20, round(f0 - (_NADA_GADIS if wanita else _NADA_ARDI))))),
                        "tau": 0.3})
    return profil()
