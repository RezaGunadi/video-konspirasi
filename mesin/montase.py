# -*- coding: utf-8 -*-
"""Montase highlight → 1 video dari folder klip b-roll / drone (TANPA transkrip, TANPA narasi tambahan).

Cocok untuk footage tanpa omongan penting (drone, aerial, b-roll, timelapse, vlog jalan-jalan). Beda dari
editfolder.py yang memotong di sekitar UCAPAN: di sini tiap klip dinilai VISUAL-nya pakai OpenCV —
kecerahan (buang gelap/over), ketajaman (Laplacian var), warna (colorfulness), dan oklusi (lensa ketutup
jari/tangan atau bidang kosong besar) — lalu diambil jendela paling bagus per klip, dipotong pendek
(±4-5 dtk), 1 potongan/klip (banyak sudut berbeda), shot kembar dibuang via dHash, disambung crossfade,
diurut kronologis (nama file = urut waktu). CPU-only (tanpa GPU): analisis pakai frame kecil + seek jarang.

Audio: klip dipertahankan apa adanya (ambient) di-crossfade; kalau folder musik/ ada isinya, dilapisi musik
(ambient diturunkan). Tidak ada transkrip Whisper → jauh lebih cepat dari editfolder untuk footage sepi.
"""
import datetime as dt
import math
import random
import subprocess
import tempfile
from pathlib import Path

import numpy as np
try:
    import cv2
    _CV = True
except Exception:                                        # cv2 hanya perlu di laptop (montase laptop-only)
    _CV = False

from .alat import FFMPEG, FFPROBE, MUSIK, OUTPUT, slug
from .editfolder import _durof, _portrait, _probe

FPS = 30
VID = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
MUS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")

AW, AH = 256, 144     # ukuran frame analisis (kecil = ringan, cukup untuk metrik + hash)
MINN, MAXN = 6, 14    # titik sampel per klip (batasi biaya untuk klip panjang)
EDGE = 1.0            # buang sekian detik di awal & akhir klip (settle / transisi)
WIN = 4.5             # panjang tiap potongan (detik)
TRANS = 0.6           # crossfade antarpotongan (detik)
FLOOR = 0.40          # skor minimal agar sebuah klip ikut (di bawah = buang)
MINSEG = 10           # kalau footage jelek semua, tetap ambil sekian potongan terbaik
DARK = 48.0           # rata-rata luma < ini = terlalu gelap (dibuang) — mis. malam / kamar gelap
BRIGHT = 230.0        # rata-rata luma > ini = over/blown (dibuang)
DEDUP_HAM = 10        # jarak Hamming dHash < ini = shot mirip (buang duplikat → variasi)


# ---------------------------------------------------------------- analisis visual (OpenCV)
# Footage 4K/1080p HEVC: decode SEMUA frame lambat. Jadi kita SEEK cepat (-ss sebelum -i) ke beberapa
# titik dan ambil 1 frame kecil tiap titik → ringan tak peduli klip sepanjang apa. Tiap frame dinilai
# pakai OpenCV: kecerahan (buang gelap/over), ketajaman (Laplacian var), warna (colorfulness), oklusi
# (lensa ketutup jari/tangan atau bidang kosong besar), plus dHash untuk membuang shot kembar.
def _grab(clip, t):
    """Seek cepat ke detik t, ambil 1 frame AWxAH BGR (numpy) atau None."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.2f}",
           "-i", str(clip), "-frames:v", "1", "-vf", f"scale={AW}:{AH}",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    try:
        buf = subprocess.run(cmd, capture_output=True, timeout=40).stdout
    except Exception:
        return None
    if len(buf) < AW * AH * 3:
        return None
    return np.frombuffer(buf[:AW * AH * 3], np.uint8).reshape(AH, AW, 3)


def _metrik(bgr):
    """Frame BGR → metrik visual (kecerahan, ketajaman, warna, oklusi, dHash)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bright = float(gray.mean())
    detail = float(cv2.Laplacian(gray, cv2.CV_64F).var())        # tinggi = tajam/berdetail
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    skin = (H <= 25) & (S >= 40) & (S <= 190) & (V >= 60)        # kulit (jari/tangan di lensa)
    gy, gx = 4, 4; hh, ww = AH // gy, AW // gx; dead = smooth_skin = 0
    for j in range(gy):
        for i in range(gx):
            c = gray[j * hh:(j + 1) * hh, i * ww:(i + 1) * ww]
            d = float(cv2.Laplacian(c, cv2.CV_64F).var())
            if d < 12.0:                                         # sel nyaris tanpa detail (kosong)
                dead += 1
            if d < 60.0 and skin[j * hh:(j + 1) * hh, i * ww:(i + 1) * ww].mean() > 0.6:
                smooth_skin += 1                                 # sel mulus & dominan kulit = ketutup
    occluded = dead / 16.0 >= 0.30 or smooth_skin / 16.0 >= 0.19
    B, G, R = [bgr[:, :, k].astype(np.float32) for k in (0, 1, 2)]
    rg = R - G; yb = 0.5 * (R + G) - B                           # colorfulness Hasler-Süsstrunk
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    g2 = cv2.resize(gray, (9, 8)); bits = (g2[:, 1:] > g2[:, :-1]).flatten()  # dHash 64-bit
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return {"bright": bright, "detail": detail, "colorful": colorful, "occluded": occluded, "hash": h}


def _skor(m):
    """Metrik → skor 0..1. Gate keras: gelap/over/oklusi = 0. Lain: tajam + eksposur + warna."""
    b = m["bright"]
    if b < DARK or b > BRIGHT:                           # terlalu gelap / over → buang
        return 0.0
    if m["occluded"]:                                    # lensa ketutup / bidang kosong besar → buang
        return 0.05
    sharp = float(np.clip((m["detail"] - 150.0) / 1200.0, 0.0, 1.0))
    expo = (float(np.clip((b - 40.0) / 55.0, 0.0, 1.0)) if b < 95.0
            else float(np.clip((230.0 - b) / 100.0, 0.0, 1.0)))
    color = float(np.clip((m["colorful"] - 8.0) / 40.0, 0.0, 1.0))
    return 0.45 * sharp + 0.25 * expo + 0.30 * color


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _jendela_terbaik(clip, dur, batal=None):
    """Sampel beberapa titik (seek cepat) → (start, skor, metrik) jendela WIN terbaik, atau m=None."""
    lo = EDGE
    hi = dur - EDGE - WIN
    if hi <= lo:                                         # klip pendek: satu jendela di tengah
        s = max(0.0, (dur - min(WIN, dur)) / 2.0)
        fr = _grab(clip, s + min(WIN, dur) / 2.0)
        if fr is None: return s, 0.0, None
        m = _metrik(fr); return s, _skor(m), m
    n = max(MINN, min(MAXN, int((hi - lo) / WIN) + 1))
    terbaik = (lo, -1.0, None)
    for i in range(n):
        if batal: batal.cek()
        s = lo + (hi - lo) * i / (n - 1)
        fr = _grab(clip, s + WIN / 2.0)
        if fr is None: continue
        m = _metrik(fr); skor = _skor(m)
        if skor > terbaik[1]:
            terbaik = (s, skor, m)
    return terbaik


# ---------------------------------------------------------------- render
def _vf(fmt):
    w, h = (1080, 1920) if fmt == "9:16" else (1920, 1080)
    return w, h, (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                  f"fps={FPS},format=yuv420p,setsar=1")


def _potong(clip, start, dur, vf, dest):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(clip),
                    "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf, "-af", "aresample=48000",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ac", "2",
                    "-shortest", str(dest)], check=True)


def _ada_audio(f):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


def _beri_audio_sunyi(seg, tmp, i):
    """Klip tanpa audio → tambah trek sunyi supaya acrossfade tidak error."""
    d = _durof(seg)
    baru = tmp / f"a{i:03d}.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(seg),
                    "-f", "lavfi", "-t", f"{d:.2f}", "-i", "anullsrc=r=48000:cl=stereo",
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", str(baru)], check=True)
    return baru


def _musik_acak():
    if not MUSIK.exists():
        return None
    lagu = [x for x in MUSIK.iterdir() if x.suffix.lower() in MUS]
    return random.choice(lagu) if lagu else None


def _render(segmen, out, fmt, log, batal=None):
    """segmen = [(clip, start, dur)] → satu video (crossfade + audio ambient, dilapis musik kalau ada)."""
    w, h, vf = _vf(fmt)
    tmp = Path(tempfile.mkdtemp(prefix="montase_"))
    segf = []
    for i, (clip, start, dur) in enumerate(segmen):
        if batal: batal.cek()
        seg = tmp / f"s{i:03d}.mp4"
        try:
            _potong(clip, start, dur, vf, seg)
        except subprocess.CalledProcessError:
            log(f"  lewati potongan gagal: {Path(clip).name}"); continue
        if _durof(seg) < 0.4:
            continue
        if not _ada_audio(seg):
            seg = _beri_audio_sunyi(seg, tmp, i)
        segf.append(seg)
    if not segf:
        raise RuntimeError("Tidak ada potongan yang bisa dirangkai")

    gabung = tmp / "gabung.mp4"
    durs = [_durof(s) for s in segf]
    if len(segf) == 1:
        gabung = segf[0]
    else:
        inputs = []
        for s in segf: inputs += ["-i", str(s)]
        fv, fa = [], []; vprev, aprev = "[0:v]", "[0:a]"; L = durs[0]
        for k in range(1, len(segf)):
            T = max(0.08, min(TRANS, durs[k - 1] / 2.0, durs[k] / 2.0))
            off = L - T
            fv.append(f"{vprev}[{k}:v]xfade=transition=fade:duration={T:.3f}:offset={off:.3f}[v{k}]")
            fa.append(f"{aprev}[{k}:a]acrossfade=d={T:.3f}[a{k}]")
            vprev, aprev = f"[v{k}]", f"[a{k}]"; L = L + durs[k] - T
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                        "-filter_complex", ";".join(fv + fa), "-map", vprev, "-map", aprev,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                        "-pix_fmt", "yuv420p", "-profile:v", "high",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(gabung)], check=True)

    total = _durof(gabung)
    lagu = _musik_acak()
    if lagu:
        log(f"  Musik dilapis: {lagu.name}")
        fade = min(2.0, total / 4.0)
        # musik di-loop, ambient asli diturunkan jadi latar tipis lalu dicampur
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(gabung), "-stream_loop", "-1", "-i", str(lagu),
                        "-filter_complex",
                        (f"[0:a]volume=0.25[amb];"
                         f"[1:a]atrim=0:{total:.2f},volume=0.85,"
                         f"afade=t=in:st=0:d={fade:.2f},afade=t=out:st={max(0.0, total-fade):.2f}:d={fade:.2f}[mus];"
                         f"[amb][mus]amix=inputs=2:duration=first:dropout_transition=0[a]"),
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    elif gabung == out:
        pass
    else:
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(gabung),
                        "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    return _durof(out)


# ---------------------------------------------------------------- entri utama
def proses(p, cfg, batal, log):
    if not _CV:
        raise RuntimeError("OpenCV (cv2) tidak tersedia — montase butuh analisis visual")
    e = p["montase"]
    folder = Path(e["folder"])
    fmt = e.get("format") or "16:9"
    target = float(e.get("durasi") or 240)               # durasi target total (detik)
    files = sorted([x for x in folder.iterdir() if x.suffix.lower() in VID])
    if not files:
        raise RuntimeError("Folder tidak berisi video")

    # orientasi: kalau output 9:16 utamakan klip portrait, selain itu landscape (biar tidak di-crop habis)
    mau_portrait = fmt == "9:16"
    klip = []
    for f in files:
        dur, w, h, rot = _probe(f)
        if dur < 1.5:
            continue
        klip.append((f, dur, _portrait(w, h, rot)))
    cocok = [(f, d) for (f, d, por) in klip if por == mau_portrait]
    if not cocok:                                         # tak ada yang se-orientasi → pakai semua (akan di-crop)
        cocok = [(f, d) for (f, d, _) in klip]
    if not cocok:
        raise RuntimeError("Tidak ada klip yang bisa dipakai")
    log(f"{len(files)} klip, {len(cocok)} dipakai untuk montase {fmt} (target ~{int(target)} dtk)")

    # nilai tiap klip (jendela terbaiknya)
    log("Menilai visual tiap klip (ketajaman / eksposur / warna / oklusi)…")
    kand = []
    for idx, (f, d) in enumerate(cocok):
        if batal: batal.cek()
        start, skor, m = _jendela_terbaik(f, d, batal)
        if m is None:
            continue
        kand.append({"clip": f, "urut": idx, "start": start, "skor": skor, "m": m})
        log(f"  [{idx+1}/{len(cocok)}] {f.name}: skor {skor:.2f} "
            f"(terang {int(m['bright'])}, detail {int(m['detail'])}, warna {m['colorful']:.0f}"
            f"{', KETUTUP' if m['occluded'] else ''})")
    if not kand:
        raise RuntimeError("Semua klip gagal dianalisis")

    # pilih: satu jendela terbaik per klip (variasi sudut maksimal), urut skor, isi sampai target.
    # Gate keras membuang shot gelap/over/ketutup (skor≈0); FLOOR membuang shot lemah; dHash membuang
    # shot kembar (mis. meja/bathtub yang sama berkali-kali) → lebih baik 3 menit rapi daripada menyelip
    # klip jelek/berulang. Kalau footage jelek SEMUA, FLOOR dilonggarkan supaya tetap ada hasil.
    kand.sort(key=lambda k: k["skor"], reverse=True)
    perlu = max(1, int(round(target / (WIN - TRANS))))
    floor = FLOOR
    if len([k for k in kand if k["skor"] >= FLOOR and not k["m"]["occluded"]]) < min(MINSEG, len(kand)):
        floor = 0.0                                      # footage jelek semua → jangan kosong
    pilih = []; b_gate = b_floor = b_dup = 0
    for k in kand:
        if len(pilih) >= perlu:
            break
        if k["skor"] <= 0.05 or k["m"]["occluded"]:      # gelap / over / lensa ketutup
            b_gate += 1; continue
        if k["skor"] < floor:
            b_floor += 1; continue
        if any(_hamming(k["m"]["hash"], q["m"]["hash"]) <= DEDUP_HAM for q in pilih):
            b_dup += 1; continue                         # shot mirip yang sudah dipilih
        pilih.append(k)
    if not pilih:                                        # pengaman terakhir
        pilih = kand[:min(MINSEG, len(kand))]
    log(f"  dibuang: {b_gate} gelap/ketutup, {b_floor} skor<{floor:.2f}, {b_dup} mirip (duplikat)")
    rata = sum(k["skor"] for k in pilih) / len(pilih)
    log(f"Dipilih {len(pilih)} potongan (skor rata-rata {rata:.2f}) dari {len(kand)} klip")

    # urut kronologis (nama file DJI = urut waktu) biar alurnya natural
    pilih.sort(key=lambda k: k["urut"])
    segmen = [(k["clip"], k["start"], WIN) for k in pilih]

    nama = slug(e.get("judul") or folder.name, 60) or "montase"
    folder_out = OUTPUT / f"{dt.datetime.now():%Y%m%d}-{nama}"
    folder_out.mkdir(parents=True, exist_ok=True)
    out = folder_out / f"{nama}.mp4"
    log("Render (potong + crossfade)…")
    durasi = _render(segmen, out, fmt, log, batal)

    p["hasil"] = {"video": str(out), "folder": str(folder_out), "durasi": round(durasi, 1),
                  "jumlah_potongan": len(segmen)}
    log(f"Selesai: {int(durasi // 60)} menit {int(durasi % 60)} detik -> {out.name}")
