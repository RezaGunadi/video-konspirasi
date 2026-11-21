# -*- coding: utf-8 -*-
"""Mesin KONTEN uploader YouTube: klasifikasi long/short, grup per-topik, jadwal "cluster rapat",
judul clickbait (sosmed-ai) + deskripsi bersih SEO + thumbnail Impact. Dipakai oleh yt_upload.py.

Model rollout "cluster rapat" (pilihan user): jalan per topik berurutan (panjang lama dulu).
Panjang tayang @07:00, short-shortnya nyusul 1/hari @17:00, baru pindah topik berikutnya →
short selalu nempel panjangnya. Short yatim (tak punya panjang se-topik) ditaruh di ekor.
"""
import math
import re
import subprocess
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------- klasifikasi
def _ffprobe():
    from mesin.alat import FFMPEG
    return Path(FFMPEG).with_name("ffprobe.exe")

def orientasi(video):
    """'short' kalau potret (tinggi>lebar), 'long' kalau lanskap. None kalau gagal."""
    try:
        r = subprocess.run([str(_ffprobe()), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, timeout=30)
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return "short" if h > w else "long"
    except Exception:
        return None

# ---------------------------------------------------------------- judul & topik
_STOP = set("""apa yang terjadi jika kalau bagaimana gimana kenapa mengapa kok bisa apakah akan saat
ketika dan atau dari pada dalam ini itu untuk buat kita kamu saya kami mereka dia ada tak tidak nggak
juga lebih paling sampai hingga seperti sebuah para nya lah pun agar supaya karena sebab jadi menjadi
tanpa dengan secara antara setiap semua banyak sedikit bukan adalah merupakan dapat harus mau ingin
telah sudah sedang masih lagi hanya saja bahkan the and for sang kah bagi tapi sains bekerja mengirim
alasannya penjelasannya faktanya rahasianya terus punya tahu benar total pernah bener""".split())

def judul_dari(video):
    """Judul = baris non-kosong pertama .txt; kalau tak ada, dari nama file."""
    txt = Path(video).with_suffix(".txt")
    if txt.exists():
        for ln in txt.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.strip():
                return ln.strip()
    return Path(video).stem.rsplit("__", 1)[0].replace("-", " ")

def _kata(judul):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (judul or "").lower()):
        w = re.sub(r"(nya|kah)$", "", w)
        if len(w) >= 3 and w not in _STOP:
            out.add(w)
    return out

def _ts(stem):
    m = re.search(r"\d{8}-\d{6}", stem)
    return m.group(0) if m else stem

def _muat_override(path):
    """JSON {substring_stem_short: substring_stem_long | "yatim"} buat koreksi manual grouping."""
    if path and Path(path).exists():
        try:
            import json as _j
            return _j.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def grup_cluster(videos, cache_path=None, override_path=None):
    """videos: list of path. Kembalikan (clusters, stats).
    clusters = urutan rollout: tiap elemen {"long": item|None, "shorts": [item]} (long lama dulu);
    cluster terakhir = semua short yatim (long=None). item = {"file","stem","judul","ori"}.
    cache_path: JSON {path|mtime: ori} biar orientasi tak di-probe ulang tiap run.
    override_path: JSON {substring_short: substring_long|"yatim"} koreksi manual (menang atas auto)."""
    import json as _json
    cache = {}
    if cache_path and Path(cache_path).exists():
        try:
            cache = _json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    items, dirty = [], False
    for v in videos:
        v = Path(v)
        try:
            ck = f"{v}|{int(v.stat().st_mtime)}"
        except OSError:
            ck = str(v)
        o = cache.get(ck)
        if o is None:
            o = orientasi(v)
            cache[ck] = o
            dirty = True
        if not o:
            continue
        j = judul_dari(v)
        items.append({"file": Path(v), "stem": Path(v).stem, "judul": j, "ori": o, "kata": _kata(j),
                      "ts": _ts(Path(v).stem)})
    if cache_path and dirty:
        try:
            Path(cache_path).write_text(_json.dumps(cache), encoding="utf-8")
        except Exception:
            pass
    df = Counter(w for x in items for w in x["kata"])
    N = max(1, len(items))
    def idf(w): return math.log((N + 1) / (df[w] + 1)) + 1.0

    longs = sorted([x for x in items if x["ori"] == "long"], key=lambda x: x["ts"])
    shorts = sorted([x for x in items if x["ori"] == "short"], key=lambda x: x["ts"])

    def skor(s, L):
        sh = s["kata"] & L["kata"]
        if not sh:
            return 0.0
        langka = [w for w in sh if df[w] <= 5]
        sedang = [w for w in sh if df[w] <= 15]
        if not (langka or len(sedang) >= 2):   # butuh 1 kata langka ATAU 2 kata lumayan-langka
            return 0.0
        return sum(idf(w) for w in sh)

    for s in shorts:
        best, bestsc = None, 0.0
        for L in longs:
            sc = skor(s, L)
            if sc > bestsc:
                best, bestsc = L, sc
        s["induk"] = best
    # koreksi manual (menang atas auto): {substring_short: substring_long | "yatim"}
    ov = _muat_override(override_path)
    for s in shorts:
        for sk, lk in ov.items():
            if sk and sk in s["stem"]:
                if not lk or str(lk).lower() == "yatim":
                    s["induk"] = None
                else:
                    tgt = next((L for L in longs if lk in L["stem"]), None)
                    if tgt:
                        s["induk"] = tgt
                break
    for L in longs:
        L["anak"] = [s for s in shorts if s.get("induk") is L]
    yatim = [s for s in shorts if s.get("induk") is None]

    clusters = [{"long": L, "shorts": L["anak"]} for L in longs]
    if yatim:
        clusters.append({"long": None, "shorts": yatim})
    stats = {"long": len(longs), "short": len(shorts), "nempel": len(shorts) - len(yatim),
             "yatim": len(yatim), "tanpa_short": sum(1 for L in longs if not L["anak"])}
    return clusters, stats

# ---------------------------------------------------------------- jadwal cluster-rapat
def jadwal(clusters, mulai, slot_long=(7, 0), slot_short=(17, 0)):
    """Kembalikan {stem: datetime_publishAt} model cluster-rapat + urutan upload (flat)."""
    hasil = {}
    urut = []
    hari = mulai
    for c in clusters:
        n = max(1, len(c["shorts"]))
        if c["long"]:
            hasil[c["long"]["stem"]] = datetime(hari.year, hari.month, hari.day, *slot_long)
            urut.append(c["long"])
        for i, s in enumerate(c["shorts"]):
            d = hari + timedelta(days=i)
            hasil[s["stem"]] = datetime(d.year, d.month, d.day, *slot_short)
            urut.append(s)
        hari = hari + timedelta(days=n)
    return hasil, urut

# ---------------------------------------------------------------- deskripsi bersih (SEO)
_POTONG = ("bahan riset", "sumber footage", "sumber footages", "sumber:", "referensi",
           "credit", "credits", "atribusi", "attribution", "sumber gambar", "sumber video")

def _hashtag_line(l):
    s = l.strip()
    return bool(s) and all(w.startswith("#") for w in s.split())

def bersih_deskripsi(raw):
    """Buang 'Sumber footage'/'Bahan riset'/'TAGS', sisakan hook + daftar isi (chapter) + hashtag.
    Kembalikan (judul_asli, teks, hashtag_line, tags)."""
    lines = raw.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    judul = lines[i].strip() if i < len(lines) else ""
    body = lines[i + 1:]
    tags = []
    for l in body:
        if l.strip().lower().startswith("tags:"):
            tags = [t.strip() for t in l.split(":", 1)[1].split(",") if t.strip()]
            break
    keep, hashtags = [], []
    for l in body:
        s = l.strip().lower()
        if any(s.startswith(p) for p in _POTONG):
            break
        if s.startswith("tags:"):
            continue
        if l.strip().startswith("▶️") or s.startswith("video lengkap"):
            continue
        if _hashtag_line(l):
            hashtags.append(l.strip())
            continue
        keep.append(l)
    teks = re.sub(r"\n{3,}", "\n\n", "\n".join(keep).strip())
    return judul, teks, " ".join(hashtags).strip(), tags

_CTA = ("🔔 Subscribe biar nggak ketinggalan fakta & sains menarik tiap hari!\n"
        "👍 Like, komen, dan bagikan ke temanmu ya.")

def rakit_deskripsi(hook, teks_bersih, hashtag_line):
    """Gabung: hook (opsional pengganti kalimat pembuka) + daftar isi + CTA + hashtag."""
    # kalau ada hook baru dari LLM, ganti paragraf pembuka lama (sebelum 'Daftar isi'/baris kosong pertama)
    teks = teks_bersih
    if hook:
        sisa = teks_bersih
        m = re.search(r"\n\s*Daftar isi\s*:", teks_bersih, re.I)
        sisa = teks_bersih[m.start():].lstrip("\n") if m else ""
        teks = (hook.strip() + ("\n\n" + sisa if sisa else "")).strip()
    bagian = [teks, _CTA] + ([hashtag_line] if hashtag_line else [])
    return "\n\n".join(b for b in bagian if b).strip()

# ---------------------------------------------------------------- judul clickbait + hook SEO
_SKEMA = {"type": "object", "properties": {
    "judul": {"type": "string"}, "thumb": {"type": "string"}, "hook": {"type": "string"}},
    "required": ["judul", "thumb", "hook"]}

def clickbait(cfg, judul_asli, desc, is_short=False, batal=None):
    """Kembalikan (judul_baru<=100, teks_thumb_2_4_kata, hook_seo). WAJIB tulis ulang judul (lebih click-bait,
    bikin penasaran, tetap jujur). hook = 1-2 kalimat pembuka bersih untuk deskripsi (parafrase, TANPA fakta baru)."""
    from mesin import ollama
    prompt = (
        "Kamu editor channel YouTube sains/fakta Indonesia (gaya 'Kok Bisa'). Dari judul & deskripsi di bawah, "
        "buat JSON berisi:\n"
        '  "judul": judul BARU (WAJIB beda & lebih menarik dari aslinya), maks 90 karakter, Bahasa Indonesia, '
        "KLIKBAIT yang bikin penasaran (boleh pertanyaan/angka/kata kuat) TAPI JUJUR sesuai isi (dilarang bohong/"
        "lebay menyesatkan). Tanpa tanda kutip, maksimal 1 emoji.\n"
        '  "thumb": 2-4 KATA super pendek HURUF BESAR untuk teks thumbnail, paling memancing penasaran.\n'
        '  "hook": 1-2 kalimat pembuka deskripsi yang rapi, natural, ber-keyword (SEO), parafrase dari deskripsi. '
        "DILARANG menambah fakta/angka yang tidak ada di sumber. Betulkan typo.\n\n"
        f"JUDUL ASLI: {judul_asli}\nDESKRIPSI: {(desc or '')[:600]}\n\nJSON:")
    h = ollama.chat_json(cfg, [{"role": "user", "content": prompt}], _SKEMA, batal=batal, suhu=0.85, maks_token=400)
    jb = (h.get("judul") or "").strip().strip('"').replace("<", "").replace(">", "")[:100] or judul_asli
    thumb = (h.get("thumb") or "").strip().upper()
    hook = (h.get("hook") or "").strip()
    return jb, thumb, hook

# ---------------------------------------------------------------- thumbnail (Impact kuning + outline)
def _frame_terbaik(video, PROBE, FF, tmp):
    from PIL import Image
    best, best_score = None, -1
    try:
        r = subprocess.run([str(PROBE), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True, timeout=30)
        dur = float(r.stdout.strip())
    except Exception:
        dur = 30.0
    for p in (0.15, 0.3, 0.45, 0.6, 0.78, 0.9):
        t = max(0.5, dur * p)
        ftmp = tmp / "f.jpg"
        subprocess.run([str(FF), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-q:v", "3", str(ftmp)], capture_output=True, timeout=60)
        if not ftmp.exists():
            continue
        im = Image.open(ftmp).convert("RGB")
        g = im.convert("L").histogram()
        n = sum(g) or 1
        mean = sum(i * g[i] for i in range(256)) / n
        score = mean - abs(mean - 140) * 0.3
        if score > best_score:
            best_score, best = score, im.copy()
    return best

def _wrap_fit(draw, text, font_path, max_w, max_h, start=170):
    from PIL import ImageFont
    words = text.split()
    for size in range(start, 40, -6):
        f = ImageFont.truetype(font_path, size)
        lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=f) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        lh = size * 1.1
        if lines and max(draw.textlength(l, font=f) for l in lines) <= max_w and lh * len(lines) <= max_h \
                and len(lines) <= 3:
            return f, lines, lh
    return ImageFont.truetype(font_path, 48), [text], 54

def buat_thumbnail(video, teks, tujuan, is_short):
    """1280x720. Short = latar blur + frame tegak tajam di tengah; long = cover-crop. Teks Impact kuning
    + outline hitam di bawah. Butuh frame cerah (dipilih dari beberapa titik)."""
    import tempfile
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    from mesin.alat import FFMPEG, font, AKAR
    FF = Path(FFMPEG)
    PROBE = FF.with_name("ffprobe.exe")
    IMPACT = font("impact")
    W, H = 1280, 720
    with tempfile.TemporaryDirectory() as td:
        fr = _frame_terbaik(video, PROBE, FF, Path(td))
    if fr is None:
        fr = Image.new("RGB", (W, H), (18, 26, 20))
    else:
        # video kita punya subtitle burned-in di bagian bawah → buang ~20% bawah biar tak ikut ke thumbnail
        fr = fr.crop((0, 0, fr.width, int(fr.height * 0.80)))
    if is_short:
        bg = fr.copy()
        s = max(W / bg.width, H / bg.height)
        bg = bg.resize((int(bg.width * s), int(bg.height * s)))
        x, y = (bg.width - W) // 2, (bg.height - H) // 2
        bg = bg.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(28))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        fw = int(fr.width * (H / fr.height))
        canvas = bg.copy()
        canvas.paste(fr.resize((fw, H)), ((W - fw) // 2, 0))
    else:
        s = max(W / fr.width, H / fr.height)
        im = fr.resize((int(fr.width * s), int(fr.height * s)))
        x, y = (im.width - W) // 2, (im.height - H) // 2
        canvas = im.crop((x, y, x + W, y + H))
    grad = Image.new("L", (1, H), 0)
    for yy in range(H):
        grad.putpixel((0, yy), int(200 * max(0, (yy - H * 0.45) / (H * 0.55))))
    canvas = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), canvas, grad.resize((W, H)))
    d = ImageDraw.Draw(canvas)
    f, lines, lh = _wrap_fit(d, teks or "?", IMPACT, W - 120, H * 0.42, start=170)
    y0 = H - lh * len(lines) - 48
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) // 2, y0 + i * lh), ln, font=f, fill=(255, 240, 20), stroke_width=10, stroke_fill=(0, 0, 0))
    # maskot Si Kepo di pojok kanan atas (branding konsisten, lepas dari framing video)
    try:
        logo_p = Path(AKAR) / "maskot" / "logo.png"
        if logo_p.exists():
            s = int(W * 0.12)
            lg = Image.open(logo_p).convert("RGBA").resize((s, s))
            canvas.paste(lg, (W - s - int(W * 0.02), int(H * 0.04)), lg)
    except Exception:
        pass
    canvas.save(tujuan, quality=90)
    return tujuan

# ---------------------------------------------------------------- dry-run kalender
def _main():
    hari_ini = datetime.now()
    dirs = [Path(r"E:/pc 1"), Path(r"E:/pc 2"), Path(r"E:/pc 3")]
    vids = [v for d in dirs if d.exists() for v in sorted(d.iterdir())
            if v.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
    clusters, st = grup_cluster(vids)
    mulai = hari_ini + timedelta(days=1)
    sched, urut = jadwal(clusters, mulai)
    HARI = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    print(f"RINGKASAN: {st['long']} panjang, {st['short']} short "
          f"({st['nempel']} nempel, {st['yatim']} yatim, {st['tanpa_short']} panjang tanpa short)")
    print(f"Jumlah hari rollout: {len(set(d.date() for d in sched.values()))}")
    # kalender: kelompokkan per tanggal
    per_hari = {}
    judul = {it["stem"]: (it["judul"], it["ori"]) for c in clusters for it in
             ([c["long"]] if c["long"] else []) + c["shorts"]}
    for stem, dt in sched.items():
        per_hari.setdefault(dt.date(), {"long": None, "short": []})
        if judul[stem][1] == "long":
            per_hari[dt.date()]["long"] = judul[stem][0]
        else:
            per_hari[dt.date()]["short"].append(judul[stem][0])
    print("\n=== KALENDER CLUSTER-RAPAT (20 hari pertama) ===")
    print(f"{'Tanggal':<13}{'07:00 PANJANG':<46}17:00 SHORT")
    for i, tgl in enumerate(sorted(per_hari)[:20]):
        row = per_hari[tgl]
        pj = (row["long"] or "—")[:44]
        sh = (row["short"][0] if row["short"] else "—")[:40]
        print(f"{HARI[tgl.weekday()]} {tgl:%d %b}  {pj:<46}{sh}")

if __name__ == "__main__":
    _main()
