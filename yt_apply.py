# -*- coding: utf-8 -*-
"""Terapkan hasil 'Minta Studio'/Gemini (judul + deskripsi + tags + thumbnail) ke SATU video YouTube
lewat API — tanpa klik manual di Studio.

Alur:
  1) Di Studio: generate judul/deskripsi/tags + 3 thumbnail pakai Minta Studio. Pilih thumbnail terbaik,
     DOWNLOAD -> simpan ke  E:\\_optim\\thumb.jpg  (atau .png).
  2) Simpan teksnya ke  E:\\_optim\\  :  judul.txt , deskripsi.txt , tags.txt
     (boleh sebagian; yang ga ada -> field lama video dibiarkan).
  3) Jalankan:  python yt_apply.py <URL-atau-ID-video>

Channel ini (mis. "Keluarga Halal Explorer") punya TOKEN sendiri (beda dari channel sains):
  Sekali:  python yt_apply.py --auth      (login Google, PILIH channel yang benar)
           python yt_apply.py --whoami    (cek token nempel di channel mana)

CATATAN: thumbnail terbaik dipilih MANUAL olehmu (penilaian visual/CTR). Script cuma nerapin.
"""
import os, re, sys, json, time, argparse
from pathlib import Path

ROOT    = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CLIENT  = RAHASIA / "yt_client.json"          # OAuth client (boleh sama dgn channel sains; client itu per-project)
TOKEN   = RAHASIA / "yt_token_khe.json"       # TOKEN khusus channel ini (beda channel = beda token)
WORKDIR = Path(r"E:\_optim")                   # tempat taruh judul.txt/deskripsi.txt/tags.txt/thumb.*

SCOPES  = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TITLE_MAX, DESC_MAX, TAGS_MAX_CHARS = 100, 4900, 460

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(time.strftime("%H:%M:%S"), t, flush=True)


def save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_creds(interactive):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request()); save_json(TOKEN, json.loads(creds.to_json())); return creds
        except Exception as e:
            log(f"refresh token gagal ({e}); perlu --auth ulang")
    if not interactive:
        raise SystemExit("Belum ada token channel ini. Jalankan dulu: python yt_apply.py --auth")
    if not CLIENT.exists():
        raise SystemExit(f"Taruh OAuth client di: {CLIENT}")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    save_json(TOKEN, json.loads(creds.to_json()))
    log(f"token tersimpan -> {TOKEN}")
    return creds


def build_service(interactive=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=get_creds(interactive), cache_discovery=False)


def whoami(svc):
    r = svc.channels().list(part="snippet,statistics", mine=True).execute()
    its = r.get("items", [])
    if not its:
        log("Token sah tapi tanpa channel?"); return None
    c = its[0]
    log(f"CHANNEL: {c['snippet']['title']}  (id {c['id']}, subs {c.get('statistics',{}).get('subscriberCount','?')})")
    return c["snippet"]["title"]


def video_id_dari(arg):
    arg = arg.strip()
    m = re.search(r"(?:v=|/shorts/|/live/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", arg)
    if m: return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", arg): return arg
    raise SystemExit(f"Ga bisa ambil video id dari: {arg}")


def baca(nama):
    p = WORKDIR / nama
    return p.read_text(encoding="utf-8", errors="ignore").strip() if p.exists() else None


def cari_thumb():
    for ext in ("jpg", "jpeg", "png"):
        p = WORKDIR / f"thumb.{ext}"
        if p.exists(): return p
    return None


def bersih_tags(raw):
    out, tot = [], 0
    for t in [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]:
        t = t.replace("<", "").replace(">", "")[:60]
        if tot + len(t) + 1 > TAGS_MAX_CHARS: break
        out.append(t); tot += len(t) + 1
    return out


def terapkan(svc, video_id, link_ke=None):
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    # 1) ambil snippet lama (categoryId WAJIB saat update; jangan sampai kehapus)
    r = svc.videos().list(part="snippet", id=video_id).execute()
    its = r.get("items", [])
    if not its:
        raise SystemExit(f"Video {video_id} ga ketemu / bukan punya channel ini.")
    snip = its[0]["snippet"]

    judul = baca("judul.txt"); desk = baca("deskripsi.txt"); tags_raw = baca("tags.txt")
    link = (link_ke or baca("link.txt") or "").strip()   # (a) short -> tautkan ke video panjang di deskripsi
    thumb = cari_thumb()
    ubah = []
    if judul:
        snip["title"] = re.sub(r"\s+", " ", judul).replace("<", "").replace(">", "")[:TITLE_MAX]; ubah.append("judul")
    # deskripsi: pakai deskripsi.txt kalau ada; lalu SISIPKAN link ke video panjang (kalau --link-ke / link.txt)
    desc_baru = desk if (desk is not None and desk != "") else None
    if link:
        base = desc_baru if desc_baru is not None else snip.get("description", "")
        if link not in base:
            base = (base.rstrip() + f"\n\n▶ Tonton VIDEO LENGKAP-nya di sini:\n{link}").strip()
        desc_baru = base
    if desc_baru is not None:
        snip["description"] = desc_baru.replace("<", "(").replace(">", ")")[:DESC_MAX]
        ubah.append("deskripsi" + ("+link" if link else ""))
    if tags_raw:
        snip["tags"] = bersih_tags(tags_raw); ubah.append(f"tags({len(snip['tags'])})")

    if not ubah and not thumb:
        raise SystemExit(f"Ga ada yang diterapkan (folder {WORKDIR} kosong dari judul/deskripsi/tags/thumb).")

    # 2) update metadata (kalau ada perubahan teks)
    if ubah:
        body = {"id": video_id, "snippet": {
            "title": snip.get("title") or "Video",
            "description": snip.get("description", ""),
            "tags": snip.get("tags", []),
            "categoryId": snip.get("categoryId", "22"),
        }}
        for k in ("defaultLanguage", "defaultAudioLanguage"):
            if snip.get(k): body["snippet"][k] = snip[k]
        svc.videos().update(part="snippet", body=body).execute()
        log(f"  metadata di-set: {', '.join(ubah)}")

    # 3) thumbnail
    if thumb:
        try:
            svc.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
            log(f"  thumbnail dipasang: {thumb.name}")
        except HttpError as e:
            log(f"  GAGAL thumbnail: {str(e)[:160]}")

    log(f"SELESAI -> https://youtu.be/{video_id}  | {snip.get('title','')[:70]}")


def main():
    global WORKDIR
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="URL atau ID video yang mau dioptimасi")
    ap.add_argument("--auth", action="store_true", help="login + pilih channel (sekali)")
    ap.add_argument("--whoami", action="store_true", help="cek token ini channel apa")
    ap.add_argument("--dir", help=f"folder bahan (default {WORKDIR})")
    ap.add_argument("--link-ke", help="URL video panjang -> ditautkan di deskripsi (buat short)")
    a = ap.parse_args()
    if a.dir: WORKDIR = Path(a.dir)
    WORKDIR.mkdir(parents=True, exist_ok=True)
    RAHASIA.mkdir(parents=True, exist_ok=True)
    if a.auth:
        whoami(build_service(interactive=True)); return
    if a.whoami:
        whoami(build_service(interactive=False)); return
    if not a.target:
        raise SystemExit("Pakai: python yt_apply.py <URL-video>  (bahan di folder E:\\_optim)")
    svc = build_service(interactive=False)
    terapkan(svc, video_id_dari(a.target), link_ke=a.link_ke)


if __name__ == "__main__":
    main()
