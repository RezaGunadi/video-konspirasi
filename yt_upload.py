# -*- coding: utf-8 -*-
"""
Uploader YouTube untuk video hasil mini PC (folder E:\\pc 1..3).
- OAuth sekali (buka browser), token disimpan di rahasia/yt_token.json -> jalan sendiri.
- Baca title/deskripsi/tags dari file .txt yang sudah ikut terunduh.
- Upload sebagai PRIVATE + publishAt (DRIP terjadwal) -> YouTube auto-publik di jam tetap.
- Anti-dobel lewat manifest rahasia/yt_uploaded.json (idempoten/resumable).
- Berhenti RAPI kalau kuota harian habis (quotaExceeded) -> lanjut besok, cuma yang sukses di-flag.

Pakai:
  python yt_upload.py --auth           # sekali: login + izinkan (pilih channel sains!)
  python yt_upload.py --whoami         # cek token ini nempel di channel mana
  python yt_upload.py --dry-run        # intip antrean + jadwal (TANPA upload)
  python yt_upload.py                  # upload sampai UPLOAD_PER_RUN hari ini
  python yt_upload.py --limit 3        # batasi jumlah run ini
  python yt_upload.py --install-task   # daftarkan Task Scheduler harian (jam 02:00)
"""
import os, sys, re, json, time, argparse, random
from pathlib import Path
from datetime import datetime, timedelta, timezone

import yt_konten as K       # mesin konten: grup topik, jadwal cluster-rapat, clickbait, deskripsi, thumbnail

# ---------------- KONFIG ----------------
ROOT    = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CLIENT  = RAHASIA / "yt_client.json"      # <- kamu taruh dari Google Cloud
TOKEN   = RAHASIA / "yt_token.json"       # dibuat otomatis saat --auth
STATE   = RAHASIA / "yt_state.json"       # {next_publish}
MANIFEST= RAHASIA / "yt_uploaded.json"    # {key: {...}} anti-dobel
THUMB   = RAHASIA / "thumb"                # thumbnail clickbait hasil generate
ORI_CACHE = RAHASIA / "yt_ori_cache.json"  # cache orientasi long/short (biar tak probe 403 tiap run)
GRUP_OVERRIDE = RAHASIA / "yt_grup_override.json"  # koreksi grouping manual {substring_short: substring_long|"yatim"}

SRC_DIRS = [Path(r"E:/pc 1"), Path(r"E:/pc 2"), Path(r"E:/pc 3")]

UPLOAD_PER_RUN = 6            # batas keras kuota API ~6/hari (1 upload = 1600 unit / 10000)
PUBLISH_SLOTS  = [(9, 0), (19, 0)]   # jam (lokal) video jadi publik -> 2/hari
MIN_LEAD_MIN   = 20          # publishAt minimal sekian menit dari sekarang
CATEGORY_ID    = "27"        # 27=Education (sains/fakta). 28=Science&Tech, 24=Entertainment
DEF_LANG       = "id"
PRIVACY        = "private"   # selalu upload private dulu
MADE_FOR_KIDS  = False       # konten edukasi umum -> bukan "dibuat untuk anak"
# Project API baru: video API dikunci PRIVATE sampai lolos Compliance Audit YouTube.
# Selama AUDITED=False -> upload private TANPA publishAt (kamu publish massal di YouTube Studio).
# Setelah audit lolos -> set True -> aktif drip auto-publik (private + publishAt).
AUDITED        = True   # 2026-11-21: probe videos.update(privacyStatus) DITERIMA -> publish/jadwal kebuka. Drip skrg set publishAt (panjang @07:00, short @17:00).
# Setelah video SUKSES ke-upload, hapus file lokalnya (E:\pc N: video + .txt/.jpg/.png) buat ngosongin storage.
# YouTube TIDAK PERNAH dihapus otomatis (hapus YT cuma manual lewat --hapus-yt). Pilihan user 2026-11-11.
HAPUS_LOKAL    = True
TITLE_MAX      = 100
DESC_MAX       = 4900
TAGS_MAX_CHARS = 460

# force-ssl = satu scope buat SEMUA: upload + baca channel + set jadwal (videos.update) + HAPUS (videos.delete).
# Ganti dari upload+readonly -> perlu --auth ulang SEKALI (token lama beda scope).
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
LOCAL_TZ = datetime.now().astimezone().tzinfo
VID_EXT  = (".mp4", ".mov", ".mkv", ".webm")


def log(t): print(time.strftime("%H:%M:%S"), t, flush=True)


def _setup_output():
    """Output aman buat run otomatis: kalau ada konsol -> paksa UTF-8 (judul ber-emoji tak
    bikin crash cp1252); kalau tanpa konsol (pythonw / Task Scheduler) -> alihkan ke
    rahasia/upload_harian.log (UTF-8) biar ada jejak + tak pernah crash 'lost sys.stdout'."""
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8")
        else:  # pythonw: stdout None -> tulis ke file log
            RAHASIA.mkdir(parents=True, exist_ok=True)
            f = open(RAHASIA / "upload_harian.log", "a", encoding="utf-8")
            sys.stdout = sys.stderr = f
            print("\n" + "=" * 54)
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "— run terjadwal")
    except Exception:
        pass


_CFG = None
def cfg_ollama():
    global _CFG
    if _CFG is None:
        from mesin import config
        _CFG = dict(config.muat(), model="sosmed-ai:latest")
    return _CFG


# ---------------- util state/manifest ----------------
def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------------- jadwal publik ----------------
def next_slot_after(dt):
    cands = []
    for day_off in (0, 1, 2):
        d = (dt + timedelta(days=day_off)).date()
        for (h, m) in PUBLISH_SLOTS:
            c = datetime(d.year, d.month, d.day, h, m, tzinfo=LOCAL_TZ)
            if c > dt:
                cands.append(c)
    return min(cands)

def ambil_next_publish():
    now = datetime.now(LOCAL_TZ)
    st = load_json(STATE, {})
    np = None
    if st.get("next_publish"):
        try: np = datetime.fromisoformat(st["next_publish"])
        except Exception: np = None
    if np is None or np <= now:
        np = next_slot_after(now)
    # jaga jarak minimal dari sekarang
    while np <= now + timedelta(minutes=MIN_LEAD_MIN):
        np = next_slot_after(np)
    return np

def simpan_next_publish(np):
    save_json(STATE, {"next_publish": np.isoformat()})


# ---------------- parse .txt ----------------
def parse_meta(txt_path, fallback_title):
    title = fallback_title
    desc = ""
    tags = []
    if txt_path.exists():
        raw = txt_path.read_text(encoding="utf-8", errors="ignore")
        lines = raw.splitlines()
        # judul = baris non-kosong pertama
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines):
            title = lines[idx].strip()
        body_lines = lines[idx + 1:]
        keep = []
        for ln in body_lines:
            s = ln.strip()
            if s.upper().startswith("TAGS:"):
                tags = [t.strip() for t in s[5:].split(",") if t.strip()]
                continue
            keep.append(ln)
        desc = "\n".join(keep).strip()
    # bersih-bersih batas YouTube
    title = re.sub(r"\s+", " ", title).strip()[:TITLE_MAX] or "Video"
    desc = desc[:DESC_MAX]
    # buang '<' '>' yang dilarang di title/desc YouTube
    title = title.replace("<", "").replace(">", "")
    desc = desc.replace("<", "(").replace(">", ")")
    # batasi total panjang tags
    out_tags, tot = [], 0
    for t in tags:
        t = t.replace("<", "").replace(">", "")[:60]
        if tot + len(t) + 1 > TAGS_MAX_CHARS:
            break
        out_tags.append(t); tot += len(t) + 1
    return title, desc, out_tags


# ---------------- kumpulkan antrean ----------------
def id_dari_nama(stem):
    # "...__20261028-144038-24c8" -> ambil bagian setelah __ buat sorting kronologis
    m = stem.rsplit("__", 1)
    return m[1] if len(m) == 2 else stem

def kumpulkan():
    man = load_json(MANIFEST, {})
    items = []
    for d in SRC_DIRS:
        if not d.exists():
            continue
        for v in d.iterdir():
            if v.suffix.lower() not in VID_EXT:
                continue
            key = v.stem
            if key in man:                      # sudah pernah diupload
                continue
            items.append((d.name, v))
    # urut kronologis (id waktu di nama file) -> lama dulu
    items.sort(key=lambda x: id_dari_nama(x[1].stem))
    return items, man


def antrean_terjadwal():
    """Kumpulkan video E:\\pc N yang belum di-manifest, grup per-topik (yt_konten), jadwalkan cluster-rapat.
    Kembalikan (antre, man, stats). antre urut-upload: {video, stem, is_short, src, publish(tz-aware)}."""
    man = load_json(MANIFEST, {})
    vids = [v for d in SRC_DIRS if d.exists() for v in d.iterdir() if v.suffix.lower() in VID_EXT]
    clusters, stats = K.grup_cluster(vids, cache_path=ORI_CACHE, override_path=GRUP_OVERRIDE)
    mulai = (datetime.now(LOCAL_TZ) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    sched, urut = K.jadwal(clusters, mulai)
    antre = []
    for it in urut:
        if it["stem"] in man:                     # sudah pernah diupload
            continue
        pub = sched.get(it["stem"])
        if pub is not None and pub.tzinfo is None:
            pub = pub.replace(tzinfo=LOCAL_TZ)
        antre.append({"video": it["file"], "stem": it["stem"], "is_short": it["ori"] == "short",
                      "src": it["file"].parent.name, "publish": pub})
    return antre, man, stats


def siapkan_konten(video, is_short):
    """Hasilkan (title_clickbait, desc_bersih_SEO, tags, thumb_path) untuk satu video.
    Judul clickbait + hook SEO via ollama (fallback aman ke judul asli); deskripsi dibersihkan dari
    'Sumber footage'/'Bahan riset'; thumbnail Impact baru. Tags ke kolom tags."""
    txt = video.with_suffix(".txt")
    raw = txt.read_text(encoding="utf-8", errors="ignore") if txt.exists() else \
        video.stem.rsplit("__", 1)[0].replace("-", " ")
    judul_asli, teks, hashtag, tags = K.bersih_deskripsi(raw)
    judul_asli = judul_asli or video.stem.rsplit("__", 1)[0].replace("-", " ")
    judul, thumb_teks, hook = judul_asli, "", ""
    try:
        judul, thumb_teks, hook = K.clickbait(cfg_ollama(), judul_asli, teks, is_short)
    except Exception as e:
        log(f"    (clickbait gagal, pakai judul asli: {str(e)[:70]})")
    desc = K.rakit_deskripsi(hook, teks, hashtag)
    title = re.sub(r"\s+", " ", judul).strip().replace("<", "").replace(">", "")[:TITLE_MAX] or "Video"
    desc = desc.replace("<", "(").replace(">", ")")[:DESC_MAX]
    out_tags, tot = [], 0
    for t in tags:
        t = t.replace("<", "").replace(">", "")[:60]
        if tot + len(t) + 1 > TAGS_MAX_CHARS:
            break
        out_tags.append(t); tot += len(t) + 1
    thumb_path = None
    try:
        THUMB.mkdir(parents=True, exist_ok=True)
        tp = THUMB / f"{video.stem}.jpg"
        K.buat_thumbnail(video, thumb_teks or title, tp, is_short)
        thumb_path = tp
    except Exception as e:
        log(f"    (thumbnail gagal, pakai lama/none: {str(e)[:70]})")
        jpg = video.with_suffix(".jpg")
        thumb_path = jpg if jpg.exists() else None
    return title, desc, out_tags, thumb_path


# ---------------- auth / service ----------------
# ---------------- multi-project (ROTASI KUOTA, headless) ----------------
# Kuota API per-project ~10000 unit/hari = ~6 upload. Buat tembus >6/hari tanpa layar/Studio:
# daftarkan beberapa project -> pas satu habis kuota, lanjut ke berikutnya (otomatis, tanpa jendela).
# Project 1 = yt_client.json / yt_token.json (kompatibel lama).
# Tambahan   = yt_client_2.json (+ yt_token_2.json), yt_client_3.json, dst — berurut.
def daftar_project():
    projs = [{"nama": "P1", "client": CLIENT, "token": TOKEN}]
    n = 2
    while True:
        c = RAHASIA / f"yt_client_{n}.json"
        if not c.exists():
            break
        projs.append({"nama": f"P{n}", "client": c, "token": RAHASIA / f"yt_token_{n}.json"})
        n += 1
    return projs


def get_creds_for(client_path, token_path, interactive):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_json(token_path, json.loads(creds.to_json()))
            return creds
        except Exception as e:
            log(f"refresh token gagal ({e}); perlu --auth ulang untuk {token_path.name}")
    if not interactive:
        raise SystemExit(f"Belum ada token sah ({token_path.name}). Jalankan dulu: python yt_upload.py --auth")
    if not client_path.exists():
        raise SystemExit(f"Taruh file OAuth client dari Google Cloud di: {client_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    save_json(token_path, json.loads(creds.to_json()))
    log(f"token tersimpan -> {token_path}")
    return creds


def build_service_for(client_path, token_path, interactive=False):
    from googleapiclient.discovery import build
    creds = get_creds_for(client_path, token_path, interactive)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# kompat lama (single project P1)
def get_creds(interactive):
    return get_creds_for(CLIENT, TOKEN, interactive)

def build_service(interactive=False):
    return build_service_for(CLIENT, TOKEN, interactive)

def whoami(svc):
    r = svc.channels().list(part="snippet,statistics", mine=True).execute()
    its = r.get("items", [])
    if not its:
        log("Token sah tapi tidak ada channel? (pastikan pilih channel yg benar saat --auth)")
        return None
    c = its[0]
    nama = c["snippet"]["title"]; cid = c["id"]
    subs = c.get("statistics", {}).get("subscriberCount", "?")
    log(f"CHANNEL: {nama}  (id {cid}, subs {subs})")
    return nama


# ---------------- hapus video ----------------
def hapus_video(svc, ids):
    from googleapiclient.errors import HttpError
    ok = 0
    for vid in ids:
        try:
            svc.videos().delete(id=vid).execute()
            log(f"  TERHAPUS {vid}"); ok += 1
        except HttpError as e:
            s = str(e)
            if "404" in s or "videoNotFound" in s:
                log(f"  (sudah tidak ada {vid}, lewati)"); ok += 1
            else:
                log(f"  GAGAL hapus {vid}: {s[:140]}")
    return ok

def bersih_lokal(video):
    """Setelah SUKSES upload: hapus file lokal (video + sidecar .txt/.jpg/.png) di E:\\pc N buat ngosongin
    storage. YouTube TIDAK disentuh. Kembalikan jumlah berkas yang terhapus."""
    video = Path(video)
    n = 0
    for p in (video, video.with_suffix(".txt"), video.with_suffix(".jpg"), video.with_suffix(".png")):
        try:
            if p.exists():
                p.unlink(); n += 1
        except Exception as e:
            log(f"    (gagal hapus lokal {p.name}: {str(e)[:60]})")
    return n


# ---------------- upload satu video ----------------
def upload_satu(svc, item):
    """item = {video, is_short, publish(tz-aware|None)}. Generate judul clickbait + deskripsi bersih +
    thumbnail, lalu upload PRIVAT (+ publishAt kalau AUDITED). Kembalikan (video_id, title)."""
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    video = item["video"]
    publish_local = item["publish"]
    title, desc, tags, thumb_path = siapkan_konten(video, item["is_short"])
    status = {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": MADE_FOR_KIDS,
              "license": "youtube", "embeddable": True}
    if AUDITED and publish_local is not None:
        status["publishAt"] = publish_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"snippet": {"title": title, "description": desc, "tags": tags, "categoryId": CATEGORY_ID,
                        "defaultLanguage": DEF_LANG, "defaultAudioLanguage": DEF_LANG},
            "status": status}
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True)
    req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    last = 0
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            pct = int(st.progress() * 100)
            if pct >= last + 20:
                log(f"    ...{pct}%"); last = pct
    vid = resp["id"]
    jenis = "SHORT  " if item["is_short"] else "PANJANG"
    if AUDITED and publish_local is not None:
        log(f"  OK {vid} [{jenis}] tayang {publish_local.strftime('%d %b %H:%M')} | {title[:50]}")
    else:
        log(f"  OK {vid} [{jenis}] PRIVAT (publish manual) | {title[:50]}")
    if thumb_path and Path(thumb_path).exists():
        try:
            svc.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb_path))).execute()
        except HttpError as e:
            log(f"    (thumbnail gagal, lanjut: {str(e)[:80]})")
    return vid, title


# ---------------- kuota habis? ----------------
def is_quota_error(e):
    s = str(e)
    return "quotaExceeded" in s or "dailyLimitExceeded" in s or "uploadLimitExceeded" in s


# ---------------- prasyarat run otomatis ----------------
TUNGGU_DRIVE_JAM = 10        # E: = hardisk eksternal USB; kalau belum dicolok, tunggu sampai sekian jam
CEK_DRIVE_MENIT  = 5

def tunggu_drive():
    """True kalau minimal satu folder E:\\pc N ada. Kalau hardisk belum dicolok, cek berkala
    (jangan sampai salah lapor 'semua sudah di-flag' padahal drivenya saja yang belum ada)."""
    batas = time.time() + TUNGGU_DRIVE_JAM * 3600
    sudah_lapor = False
    while True:
        if any(d.exists() for d in SRC_DIRS):
            if sudah_lapor:
                log("Hardisk E: terdeteksi, lanjut.")
            return True
        if not sudah_lapor:
            log(f"Hardisk E: belum terpasang (folder pc 1..3 tidak ada). Menunggu s/d {TUNGGU_DRIVE_JAM} jam, cek tiap {CEK_DRIVE_MENIT} menit...")
            sudah_lapor = True
        if time.time() >= batas:
            log("Hardisk E: tetap tidak ada. Run ini dibatalkan; tidak ada yang diupload.")
            return False
        time.sleep(CEK_DRIVE_MENIT * 60)


def pastikan_ollama():
    """Ollama di laptop tidak auto-start -> nyalakan 'ollama serve' tanpa jendela kalau belum jalan,
    biar judul clickbait tetap dibuat (kalau gagal, yt_konten tetap fallback ke judul asli)."""
    import shutil, subprocess, urllib.request
    url = cfg_ollama().get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    def hidup():
        try:
            urllib.request.urlopen(url, timeout=5).read()
            return True
        except Exception:
            return False
    if hidup():
        return True
    exe = shutil.which("ollama") or r"D:\tools\Ollama\ollama.exe"
    if not Path(exe).exists():
        log("Ollama tidak ditemukan -> judul pakai versi asli.")
        return False
    try:
        flags = 0x08000000 | 0x00000008   # CREATE_NO_WINDOW | DETACHED_PROCESS
        subprocess.Popen([exe, "serve"], creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"Gagal menyalakan Ollama ({e}) -> judul pakai versi asli.")
        return False
    for _ in range(30):
        time.sleep(2)
        if hidup():
            log("Ollama dinyalakan otomatis.")
            return True
    log("Ollama tidak merespons -> judul pakai versi asli.")
    return False


# ---------------- main run ----------------
def run_upload(limit):
    from googleapiclient.errors import HttpError
    if not tunggu_drive():
        return
    pastikan_ollama()
    svc = build_service(interactive=False)
    nama = whoami(svc)
    if nama is None:
        return
    antre, man, stats = antrean_terjadwal()
    if not antre:
        log("Tidak ada video baru untuk diupload (semua sudah di-flag). Selesai.")
        return
    n = min(limit if limit else UPLOAD_PER_RUN, UPLOAD_PER_RUN, len(antre))
    mode = "drip auto-publik" if AUDITED else "PRIVAT (publish manual di Studio)"
    log(f"Antre {len(antre)} video; upload {n} run ini. Channel: {nama} | mode: {mode}")
    sukses = 0
    for i in range(n):
        item = antre[i]
        key, video = item["stem"], item["video"]
        try:
            vid, title = upload_satu(svc, item)
        except HttpError as e:
            if is_quota_error(e):
                log("KUOTA HARIAN HABIS -> berhenti rapi, lanjut besok (yang sukses sudah di-flag).")
                break
            log(f"  GAGAL (skip) {key}: {str(e)[:140]}")
            continue
        except Exception as e:
            log(f"  ERROR (skip) {key}: {str(e)[:140]}")
            continue
        # sukses -> catat manifest SEGERA (tahan crash). publish_at disimpan walau pra-audit (utk --apply-schedule).
        pub = item["publish"]
        man[key] = {"video_id": vid, "title": title, "src": item["src"], "is_short": item["is_short"],
                    "publish_at": (pub.isoformat() if pub else "manual"),
                    "diterapkan": bool(AUDITED and pub),
                    "uploaded_at": datetime.now(LOCAL_TZ).isoformat()}
        save_json(MANIFEST, man)
        if HAPUS_LOKAL:          # sukses upload -> hapus file lokal E:\pc N (YouTube tak disentuh)
            nh = bersih_lokal(video)
            man[key]["lokal_dihapus"] = nh > 0
            save_json(MANIFEST, man)
            log(f"    lokal dihapus ({nh} berkas) — storage lega; YouTube aman")
        sukses += 1
        time.sleep(2)
    log(f"Selesai run: {sukses} terupload. Sisa antre ~{len(antre) - sukses}.")


def dry_run(limit):
    try:
        whoami(build_service(interactive=False))
    except SystemExit as e:
        log(f"(info: {e}) — tetap tampilkan antrean & jadwal.")
    antre, man, stats = antrean_terjadwal()
    mode = "drip auto-publik" if AUDITED else "PRIVAT (publish manual; publishAt disimpan utk pasca-audit)"
    log(f"Sudah terupload: {len(man)} | antre: {len(antre)}  "
        f"({stats['long']} panjang, {stats['short']} short, {stats['yatim']} short yatim)")
    log(f"Mode: {mode}")
    n = min(limit if limit else UPLOAD_PER_RUN, len(antre))
    log(f"--- {n} video berikutnya (urut cluster-rapat: panjang @07:00, short @17:00) ---")
    for it in antre[:n]:
        when = it["publish"].strftime("%a %d %b %H:%M") if it["publish"] else "-"
        log(f"  [{'SHORT  ' if it['is_short'] else 'PANJANG'}] {when} | {it['video'].stem[:52]}")
    contoh = min(2, n)
    if contoh:
        log(f"--- contoh konten hasil generate ({contoh} video; ollama + thumbnail) ---")
        for it in antre[:contoh]:
            try:
                title, desc, tags, thumb = siapkan_konten(it["video"], it["is_short"])
                log(f"  • asli : {it['video'].stem.rsplit('__', 1)[0].replace('-', ' ')[:54]}")
                log(f"    judul: {title}")
                log(f"    thumb: {thumb}")
                log(f"    tags : {len(tags)} | deskripsi {len(desc)} char")
            except Exception as e:
                log(f"    (gagal generate: {str(e)[:90]})")
    log("(ini --dry-run; tidak ada yang diupload)")


def install_task(jam="10:00"):
    import subprocess, tempfile
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")          # tanpa jendela konsol
    exe = pyw if pyw.exists() else py
    hh, mm = (jam.split(":") + ["0"])[:2]
    start = f"{datetime.now():%Y-%m-%d}T{int(hh):02d}:{int(mm):02d}:00"
    script = ROOT / "yt_upload.py"
    # XML (bukan /SC DAILY biasa) supaya bisa StartWhenAvailable: laptop mati pas jadwal -> jalan pas nyala
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Upload 6 video sains/hari ke YouTube (privat, cluster-rapat).</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe}</Command>
      <Arguments>"{script}"</Arguments>
      <WorkingDirectory>{ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
    tmp = Path(tempfile.gettempdir()) / "yt_uploader_task.xml"
    tmp.write_text(xml, encoding="utf-16")
    cmd = ["schtasks", "/Create", "/TN", "YT Uploader Sains", "/XML", str(tmp), "/F"]
    log(f"Mendaftarkan Task Scheduler harian {jam} (StartWhenAvailable=on) ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout or "", r.stderr or "")
    if r.returncode == 0:
        log('OK. Cek: schtasks /Query /TN "YT Uploader Sains" /V /FO LIST')
    else:
        log("Gagal daftar task (jalankan dari terminal user biasa; XML ada di %TEMP%).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true", help="login + izinkan (sekali)")
    ap.add_argument("--whoami", action="store_true", help="cek channel token")
    ap.add_argument("--dry-run", action="store_true", help="intip antrean tanpa upload")
    ap.add_argument("--limit", type=int, default=0, help="batasi jumlah upload run ini")
    ap.add_argument("--install-task", action="store_true", help="daftar Task Scheduler harian")
    ap.add_argument("--hapus-yt", nargs="+", metavar="VIDEO_ID",
                    help="MANUAL saja: hapus video YouTube by id (cleanup otomatis TAK pernah hapus YouTube)")
    a = ap.parse_args()
    RAHASIA.mkdir(parents=True, exist_ok=True)
    _setup_output()
    if a.install_task:
        install_task(); return
    if a.auth:
        svc = build_service(interactive=True); whoami(svc); return
    if a.hapus_yt:
        svc = build_service(interactive=False); whoami(svc); hapus_video(svc, a.hapus_yt); return
    if a.whoami:
        whoami(build_service(interactive=False)); return
    if a.dry_run:
        dry_run(a.limit); return
    run_upload(a.limit)


if __name__ == "__main__":
    main()
