# -*- coding: utf-8 -*-
"""Montase highlight → 1 video dari folder klip b-roll / drone (TANPA transkrip, TANPA narasi tambahan).

Cocok untuk footage tanpa omongan penting (drone, aerial, b-roll, timelapse). Beda dari editfolder.py yang
memotong di sekitar UCAPAN: di sini tiap klip dinilai VISUAL-nya — ketajaman (blurdetect), eksposur
(signalstats YAVG), gerak (YDIF), dan potongan keras (scdet) — lalu diambil jendela paling bagus per klip,
dipotong pendek (±4-5 dtk), divariasikan antarklip (maksimal 1-2 potongan/klip → banyak sudut berbeda),
disambung crossfade, diurut kronologis (nama file DJI = urut waktu). CPU-only (tanpa GPU): analisis pakai
resolusi kecil + frame jarang supaya ringan.

Audio: klip dipertahankan apa adanya (ambient) di-crossfade; kalau folder musik/ ada isinya, dilapisi musik
(ambient diturunkan). Tidak ada transkrip Whisper → jauh lebih cepat dari editfolder untuk footage sepi.
"""
import datetime as dt
import math
import random
import subprocess
import tempfile
from pathlib import Path

from .alat import FFMPEG, FFPROBE, MUSIK, OUTPUT, slug
from .editfolder import _durof, _portrait, _probe

FPS = 30
VID = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
MUS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")

ANALYZE_W = 200       # lebar frame analisis (kecil = ringan, cukup untuk blur/eksposur)
SAMPLE_FPS = 2        # frame/detik yang didecode di tiap titik sampel
PROBE = 1.0           # lama decode tiap titik sampel (detik) — diseek cepat lewat -ss
MAXN = 24             # maksimal titik sampel per klip (batasi biaya untuk klip panjang)
MINN = 5              # minimal titik sampel per klip
EDGE = 1.0            # buang sekian detik di awal & akhir klip (take-off / gimbal settle / mendarat)
WIN = 4.5             # panjang tiap potongan (detik)
TRANS = 0.6           # crossfade antarpotongan (detik)
FLOOR = 0.45          # skor minimal agar sebuah klip ikut (di bawah ini = buram/gelap, dibuang)
MINSEG = 8            # kalau footage jelek semua, tetap ambil sekian potongan terbaik


# ---------------------------------------------------------------- analisis visual (sampling seek)
# Footage drone biasanya 4K/1080p HEVC: men-decode SEMUA frame lambat. Jadi kita SEEK cepat (-ss sebelum
# -i, lompat ke keyframe) ke beberapa titik lalu decode ~1 detik saja di tiap titik → ratusan kali lebih
# ringan, tak peduli klip sepanjang apa. Metrik yang andal per-frame: ketajaman (blurdetect, kecil=tajam),
# eksposur (YAVG), dan warna (SATAVG). Gerak tidak dipakai karena tak terukur andal dari sampel pendek.
def _probe_titik(clip, center):
    """Seek ke `center`, decode ~PROBE detik → rata-rata {blur, yavg, sat} atau None."""
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-ss", f"{max(0.0, center):.2f}", "-i", str(clip),
           "-t", f"{PROBE:.2f}",
           "-vf", (f"scale={ANALYZE_W}:-2,format=yuv420p,fps={SAMPLE_FPS},"
                   f"blurdetect,signalstats,metadata=print:file=-"),
           "-an", "-f", "null", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return None
    blur = yavg = sat = 0.0; n = 0
    cb = cy = cs = None
    def simpan():
        nonlocal blur, yavg, sat, n, cb, cy, cs
        if cb is not None and cy is not None:
            blur += cb; yavg += cy; sat += (cs or 0.0); n += 1
        cb = cy = cs = None
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("frame:"):
            simpan()
        elif "=" in ln:
            k, _, v = ln.partition("=")
            try: fv = float(v)
            except ValueError: continue
            if k == "lavfi.blur": cb = fv
            elif k == "lavfi.signalstats.YAVG": cy = fv
            elif k == "lavfi.signalstats.SATAVG": cs = fv
    simpan()
    if not n:
        return None
    return {"blur": blur / n, "yavg": yavg / n, "sat": sat / n}


def _nilai(m):
    """Metrik rata-rata satu titik → (skor 0..1, detail). Tinggi = tajam, eksposur pas, berwarna."""
    blur, yavg, sat = m["blur"], m["yavg"], m["sat"]
    sharp = 1.0 / (1.0 + blur / 8.0)                     # blur 5→0.62, 10→0.44, 25→0.24
    expo = max(0.0, 1.0 - abs(yavg - 130.0) / 110.0)     # ideal ±130; gelap/over → 0
    satb = min(1.0, sat / 55.0)                          # bonus warna (hazy ~5 → 0.09)
    skor = 0.55 * sharp + 0.30 * expo + 0.15 * satb
    return skor, {"blur": round(blur, 1), "yavg": round(yavg), "sat": round(sat, 1),
                  "sharp": round(sharp, 2), "expo": round(expo, 2)}


def _jendela_terbaik(clip, dur, batal=None):
    """Sampel beberapa titik (seek cepat) → (start, skor, detail) jendela WIN terbaik."""
    lo = EDGE
    hi = dur - EDGE - WIN
    if hi <= lo:                                         # klip pendek: satu jendela di tengah
        s = max(0.0, (dur - min(WIN, dur)) / 2.0)
        m = _probe_titik(clip, s + min(WIN, dur) / 2.0)
        if not m: return s, 0.0, {}
        skor, det = _nilai(m); return s, skor, det
    n = max(MINN, min(MAXN, int((hi - lo) / WIN) + 1))
    terbaik = (lo, -1.0, {})
    for i in range(n):
        if batal: batal.cek()
        s = lo + (hi - lo) * i / (n - 1)
        m = _probe_titik(clip, s + WIN / 2.0)
        if not m: continue
        skor, det = _nilai(m)
        if skor > terbaik[1]:
            terbaik = (s, skor, det)
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
    log("Menilai visual tiap klip (ketajaman / eksposur / warna)…")
    kand = []
    for idx, (f, d) in enumerate(cocok):
        if batal: batal.cek()
        start, skor, det = _jendela_terbaik(f, d, batal)
        if not det:
            continue
        kand.append({"clip": f, "urut": idx, "start": start, "skor": skor, "det": det})
        log(f"  [{idx+1}/{len(cocok)}] {f.name}: skor {skor:.2f} "
            f"(blur {det.get('blur')}, terang {det.get('yavg')}, warna {det.get('sat')})")
    if not kand:
        raise RuntimeError("Semua klip gagal dianalisis")

    # pilih: ambil jendela terbaik tiap klip dulu (variasi sudut maksimal), urut skor; isi sampai target.
    # Buang klip yang kelewat buram/gelap (skor < FLOOR) walau montase jadi lebih pendek — lebih baik 3 menit
    # shot bagus daripada menyelipkan klip jelek. Kalau footage jelek SEMUA, tetap ambil yang terbaik.
    kand.sort(key=lambda k: k["skor"], reverse=True)
    perlu = max(1, int(round(target / (WIN - TRANS))))
    layak = [k for k in kand if k["skor"] >= FLOOR]
    if len(layak) < min(MINSEG, len(kand)):
        layak = kand[:min(MINSEG, len(kand))]
    dibuang = len(kand) - len(layak)
    if dibuang:
        log(f"  {dibuang} klip dibuang karena buram/gelap (skor < {FLOOR})")
    pilih = layak[:perlu]
    if len(pilih) < perlu:                               # klip layak habis → biarkan apa adanya
        log(f"  klip layak hanya {len(pilih)}, montase akan lebih pendek dari target")
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
