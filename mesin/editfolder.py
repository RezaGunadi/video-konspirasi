# -*- coding: utf-8 -*-
"""Edit Folder → 1 video matang (cut & rangkai, TANPA narasi tambahan — audio asli dipertahankan).

Alur: pisah klip landscape vs portrait → transkrip klip landscape (Whisper) → AI (Ollama) memilih bagian
penting & menyusun urut "utama → sampingan" → render: potong tepat di akhir kata, sambung dengan crossfade
adaptif (ada jeda = dissolve halus; rapat = potong cepat), ditutup b-roll sunyi untuk dubbing.
Klip portrait dipisah sebagai bahan Reels (tidak masuk montase landscape).

Catatan seleksi AI: memakai ID segmen GLOBAL (satu angka 0..N) supaya model tidak salah indeks, lalu
divalidasi (indeks dalam rentang + rasio simpan wajar). Model besar (gemma) lebih akurat dari sosmed-ai.
"""
import datetime as dt
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ollama, recreate
from .alat import FFMPEG, FFPROBE, OUTPUT, slug

OUT_W, OUT_H, FPS = 1920, 1080, 30
TRANS = 0.45       # crossfade maksimal (saat ada cukup hening)
PAD = 0.6          # perpanjang shot ke hening maks sekian detik tiap ujung
VF = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
      f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p,setsar=1")
VID = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
MODEL_PILIH = "gemma4:12b-it-qat"   # dipakai untuk langkah seleksi kalau tersedia (lebih akurat dari sosmed-ai)
_URUT = {"intro": 0, "pembuka": 0, "utama": 1, "inti": 1, "produk": 1, "makanan": 1,
         "suasana": 2, "fasilitas": 3, "sampingan": 3, "penutup": 4, "closing": 4}


# ---------------------------------------------------------------- util media
def _probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height,duration:stream_side_data=rotation",
                          "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    d = json.loads(out or "{}")
    st = (d.get("streams") or [{}])[0]
    dur = float(st.get("duration") or d.get("format", {}).get("duration") or 0)
    rot = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    return dur, int(st.get("width") or 0), int(st.get("height") or 0), rot


def _portrait(w, h, rot):
    if rot in (90, -90, 270, -270):
        return True
    return h > w


def _durof(f):
    o = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True).stdout.strip()
    try: return float(o)
    except: return 0.0


# ---------------------------------------------------------------- transkrip + ID global
def _transkrip(land, log):
    """trs = transkrip per klip; G = [(ki, si)] segmen BERISI kata; teks = 'gi: kalimat' per baris."""
    trs, G, baris = [], [], []
    for ki, f in enumerate(land):
        try:
            segs = recreate.transkrip_file(f, log=log)
        except Exception as e:
            log(f"  transkrip gagal {Path(f).name}: {e}"); segs = []
        trs.append(segs)
        for si, s in enumerate(segs):
            t = " ".join((s.get("teks") or "").split())
            if len(t) >= 2:
                baris.append(f"{len(G)}: {t}")
                G.append((ki, si))
    return trs, G, "\n".join(baris)


# ---------------------------------------------------------------- seleksi AI (ID global + validasi)
_SCHEMA = {
    "type": "object",
    "properties": {
        "simpan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dari": {"type": "integer"},
                    "sampai": {"type": "integer"},
                    "bagian": {"type": "string"},
                },
                "required": ["dari", "sampai"],
            },
        }
    },
    "required": ["simpan"],
}


def _model_tersedia(cfg):
    try:
        ada = set(ollama.daftar_model(cfg))
    except Exception:
        ada = set()
    for m in (MODEL_PILIH, MODEL_PILIH.split(":")[0]):
        for a in ada:
            if a == m or a.startswith(m):
                return a
    return cfg["model"]


def _pilih_ai(cfg, G, trs, teks, log, batal=None):
    """Kembalikan daftar blok [{klip,awal,akhir,bagian,pos}] hasil seleksi AI, atau None kalau gagal/takmasuk akal.
    LLM tak konsisten soal BERAPA BANYAK yang diambil, jadi: kasih target ~60% di prompt, ulang sampai 3x,
    pakai percobaan yang jatuh di band 0.40-0.80 (kalau tak ada, ambil yang paling penuh di bawah 0.92)."""
    n = len(G)
    model = _model_tersedia(cfg)
    cfg2 = dict(cfg, model=model)
    target = max(1, int(round(n * 0.6)))
    prompt = (
        "Kamu editor video. Di bawah ada transkrip (tiap baris: NOMOR: kalimat). Pilih kalimat yang penting "
        "untuk video jadi yang enak ditonton, lalu kelompokkan & urutkan dari UTAMA ke SAMPINGAN.\n"
        "Aturan:\n"
        "- Buang HANYA obrolan tak penting, pengulangan, basa-basi, salah ucap, jeda, dan kalimat kosong/cuma bunyi.\n"
        "- Sisanya SIMPAN. Lebih baik kepanjangan daripada ada info penting hilang.\n"
        "- Keluarkan rentang NOMOR berurutan yang disimpan, mis. {\"dari\":5,\"sampai\":9}. Gabung nomor-nomor "
        "berdekatan jadi satu rentang panjang, jangan satu-satu.\n"
        "- 'bagian' salah satu: intro, utama, suasana, fasilitas, penutup. 'utama' = inti (produk/makanan/penjelasan "
        "pokok); fasilitas & hal sampingan ditaruh belakangan.\n"
        f"- NOMOR hanya 0 sampai {n - 1}. Jangan mengarang nomor di luar itu.\n"
        f"- Simpan SEKITAR {target} dari {n} kalimat (kira-kira 50-70%). JANGAN cuma sedikit.\n\n"
        f"TRANSKRIP ({n} kalimat):\n{teks}\n\n"
        "JSON: {\"simpan\":[{\"dari\":int,\"sampai\":int,\"bagian\":str}, ...]} urut sesuai alur tayang."
    )

    def dur_seg(gi):
        ki, si = G[gi]; s = trs[ki][si]; return max(0.0, s["t1"] - s["t0"])
    tot = sum(dur_seg(i) for i in range(n)) or 1

    def satu():
        """Satu panggilan model -> (kept gi->bagian, rasio) atau None."""
        try:
            hasil = ollama.chat_json(cfg2, [{"role": "user", "content": prompt}], _SCHEMA,
                                     batal=batal, suhu=0.2, maks_token=6000)
        except Exception as e:
            log(f"  AI gagal ({e})"); return None
        kept = {}
        for r in (hasil.get("simpan") or []):
            try:
                a = int(r.get("dari")); b = int(r.get("sampai"))
            except Exception:
                continue
            if b < a:
                a, b = b, a
            a = max(0, a); b = min(n - 1, b)
            sec = str(r.get("bagian") or "utama").lower().strip()
            for gi in range(a, b + 1):
                kept.setdefault(gi, sec)
        if not kept:
            return None
        return kept, sum(dur_seg(i) for i in kept) / tot

    log(f"  AI memilih pakai model {model} (bisa beberapa menit; target ~{target}/{n})…")
    terbaik = None   # (kept, rasio) dengan rasio tertinggi yang <0.92
    for coba in range(3):
        if batal: batal.cek()
        r = satu()
        if r is None:
            continue
        kept, rasio = r
        log(f"  percobaan {coba+1}: AI simpan {len(kept)}/{n} kalimat (~{rasio*100:.0f}% durasi)")
        if rasio > 0.92:                       # hampir semua -> tak menyaring, lewati
            continue
        if terbaik is None or rasio > terbaik[1]:
            terbaik = (kept, rasio)
        if 0.40 <= rasio <= 0.80:              # sudah di band bagus -> cukup
            break
    if terbaik is None:
        log("  AI tak mengembalikan indeks valid/masuk akal"); return None
    kept, rasio = terbaik
    if rasio < 0.25:
        log(f"  AI terlalu sedikit ({rasio*100:.0f}%) walau diulang — seleksi diabaikan"); return None
    log(f"  dipakai: {len(kept)}/{n} kalimat (~{rasio*100:.0f}% durasi)")
    # bangun blok: gi berurutan, klip sama, si kontigu
    blocks, run = [], None
    for gi, (ki, si) in enumerate(G):
        if gi in kept:
            sec = kept[gi]
            if run and run["klip"] == ki and si == run["akhir"] + 1:
                run["akhir"] = si
            else:
                if run: blocks.append(run)
                run = {"klip": ki, "awal": si, "akhir": si, "bagian": sec, "pos": gi}
        elif run:
            blocks.append(run); run = None
    if run: blocks.append(run)
    blocks.sort(key=lambda b: (_URUT.get(b["bagian"], 1), b["pos"]))
    return blocks


def _fallback_blok(trs):
    """AI gagal: ambil semua segmen tiap klip (dead air antar-segmen tetap dibuang saat render)."""
    return [{"klip": ki, "awal": 0, "akhir": len(segs) - 1, "bagian": "utama"}
            for ki, segs in enumerate(trs) if segs]


# ---------------------------------------------------------------- render
def _render(land, trs, blok, out, tutup, log, batal=None):
    tmp = Path(tempfile.mkdtemp(prefix="editfolder_"))
    segf, pads = [], []
    for b in blok:
        if batal: batal.cek()
        ki = b["klip"]
        if ki < 0 or ki >= len(land) or not trs[ki]:
            continue
        segs = trs[ki]
        ai = max(0, min(int(b["awal"]), len(segs) - 1))
        aj = max(ai, min(int(b["akhir"]), len(segs) - 1))
        clip = str(land[ki]); cdur = _durof(clip)
        t0 = segs[ai]["t0"]; t1 = segs[aj]["t1"]
        lead = t0 - (segs[ai - 1]["t1"] if ai > 0 else 0.0)
        trail = (segs[aj + 1]["t0"] if aj + 1 < len(segs) else cdur) - t1
        hp = min(PAD, max(0.0, lead)); tp = min(PAD, max(0.0, trail))
        ss = max(0.0, t0 - hp); dur = (t1 + tp) - ss
        if dur < 0.4:
            continue
        seg = tmp / f"s{len(segf):03d}.mp4"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}", "-i", clip,
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", VF, "-af", "aresample=48000",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(seg)], check=True)
        segf.append(seg); pads.append((hp, tp))
    if not segf:
        raise RuntimeError("Tidak ada bagian yang bisa dirangkai")

    if tutup:
        src = max(land, key=lambda f: _durof(f)); d = _durof(src)
        ss = max(0.0, d * 0.5); t = min(14.0, max(4.0, d - ss - 0.2))
        seg = tmp / f"s{len(segf):03d}.mp4"
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{ss:.2f}", "-t", f"{t:.2f}", "-i", str(src),
                        "-f", "lavfi", "-t", f"{t:.2f}", "-i", "anullsrc=r=48000:cl=stereo",
                        "-filter_complex", f"[0:v]{VF}[v]", "-map", "[v]", "-map", "1:a",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ac", "2", str(seg)], check=True)
        segf.append(seg); pads.append((TRANS, TRANS))

    durs = [_durof(s) for s in segf]
    if len(segf) == 1:
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(segf[0]),
                        "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
        return _durof(out)
    inputs = []
    for s in segf: inputs += ["-i", str(s)]
    fv, fa = [], []; vprev, aprev = "[0:v]", "[0:a]"; L = durs[0]
    for k in range(1, len(segf)):
        T = max(0.08, min(TRANS, pads[k - 1][1], pads[k][0]))
        off = L - T
        fv.append(f"{vprev}[{k}:v]xfade=transition=fade:duration={T:.3f}:offset={off:.3f}[v{k}]")
        fa.append(f"{aprev}[{k}:a]acrossfade=d={T:.3f}[a{k}]")
        vprev, aprev = f"[v{k}]", f"[a{k}]"; L = L + durs[k] - T
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                    "-filter_complex", ";".join(fv + fa), "-map", vprev, "-map", aprev,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
                    "-pix_fmt", "yuv420p", "-profile:v", "high",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)
    return _durof(out)


# ---------------------------------------------------------------- entri utama
def proses(p, cfg, batal, log):
    e = p["edit"]
    folder = Path(e["folder"])
    files = sorted([x for x in folder.iterdir() if x.suffix.lower() in VID])
    if not files:
        raise RuntimeError("Folder tidak berisi video")
    land, portrait = [], []
    for f in files:
        dur, w, h, rot = _probe(f)
        if dur < 1.0:
            continue
        (portrait if _portrait(w, h, rot) else land).append(f)
    log(f"{len(files)} klip: {len(land)} landscape, {len(portrait)} portrait")
    if not land:
        raise RuntimeError("Tidak ada klip landscape untuk montase (semua portrait?)")

    log("Transkrip klip landscape (Whisper)…")
    if batal: batal.cek()
    trs, G, teks = _transkrip(land, log)
    if not teks.strip():
        log("Tidak ada ucapan terdeteksi — rangkai semua klip apa adanya")
        blok = _fallback_blok(trs)
    else:
        log("AI memilih & menyusun bagian penting…")
        if batal: batal.cek()
        blok = _pilih_ai(cfg, G, trs, teks, log, batal)
        if not blok:
            log("Seleksi AI gagal/diabaikan — pakai semua bicara (dead air tetap dibuang)")
            blok = _fallback_blok(trs)

    nama = slug(e.get("judul") or folder.name, 60) or "edit-folder"
    folder_out = OUTPUT / f"{dt.datetime.now():%Y%m%d}-{nama}"
    folder_out.mkdir(parents=True, exist_ok=True)
    out = folder_out / f"{nama}.mp4"
    log("Render (potong + crossfade adaptif)…")
    durasi = _render(land, trs, blok, out, e.get("tutup_broll", True), log, batal)

    reels = []
    if portrait:
        rdir = folder_out / "reels-portrait"; rdir.mkdir(exist_ok=True)
        for f in portrait:
            tujuan = rdir / f.name
            if not tujuan.exists():
                shutil.copy2(f, tujuan)
            reels.append(str(tujuan))
        log(f"{len(portrait)} klip portrait disalin ke folder reels-portrait")

    p["hasil"] = {"video": str(out), "folder": str(folder_out), "durasi": round(durasi, 1),
                  "reels_portrait": reels}
    log(f"Selesai: {int(durasi // 60)} menit {int(durasi % 60)} detik -> {out.name}")
