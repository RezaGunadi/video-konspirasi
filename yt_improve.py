# -*- coding: utf-8 -*-
"""Terapkan metadata IMPROVED (judul/deskripsi/tags [+thumbnail]) ke video yang sudah ada, via API.
Baca rahasia/sains_improve.json = [{id, title?, description?, tags?[], thumb?}]. Hanya field yg ada yg diubah.
categoryId & bahasa lama DIPERTAHANKAN. videos.update = 50 unit; thumbnails.set bila 'thumb' ada.

  python yt_improve.py --token yt_token.json --dry-run           # lihat yg bakal diubah (tanpa apply)
  python yt_improve.py --token yt_token.json --test              # apply 1 video pertama (tes API)
  python yt_improve.py --token yt_token.json --limit 10          # apply 10
  python yt_improve.py --token yt_token.json                     # apply semua
"""
import sys, json, time, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
IMPROVE = RAHASIA / "sains_improve.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(time.strftime("%H:%M:%S"), t, flush=True)

def build_service(token_path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request()); token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def terapkan_satu(svc, item):
    from googleapiclient.errors import HttpError
    r = svc.videos().list(part="snippet", id=item["id"]).execute()
    its = r.get("items", [])
    if not its: return "hilang"
    snip = its[0]["snippet"]
    if item.get("title"): snip["title"] = item["title"][:100]
    if item.get("description") is not None: snip["description"] = item["description"][:4900]
    if item.get("tags") is not None: snip["tags"] = item["tags"]
    body = {"id": item["id"], "snippet": {
        "title": snip.get("title") or "Video", "description": snip.get("description", ""),
        "tags": snip.get("tags", []), "categoryId": snip.get("categoryId", "27")}}
    for k in ("defaultLanguage", "defaultAudioLanguage"):
        if snip.get(k): body["snippet"][k] = snip[k]
    svc.videos().update(part="snippet", body=body).execute()
    if item.get("thumb") and Path(item["thumb"]).exists():
        from googleapiclient.http import MediaFileUpload
        try: svc.thumbnails().set(videoId=item["id"], media_body=MediaFileUpload(item["thumb"])).execute()
        except HttpError as e: log(f"    (thumbnail gagal: {str(e)[:90]})")
    return "ok"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="yt_token.json")
    ap.add_argument("--test", action="store_true", help="apply 1 video pertama")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if not IMPROVE.exists(): raise SystemExit(f"Belum ada {IMPROVE}")
    items = json.loads(IMPROVE.read_text(encoding="utf-8"))
    if a.test: items = items[:1]
    elif a.limit: items = items[:a.limit]
    log(f"{len(items)} video akan di-improve (sumber {IMPROVE.name})")
    if a.dry_run:
        for it in items:
            log(f"  {it['id']} | judul: {(it.get('title') or '(tetap)')[:70]}")
            log(f"     tags {len(it.get('tags') or [])} | desc {len(it.get('description') or '')}c | thumb {'Y' if it.get('thumb') else '-'}")
        log("(dry-run; tak ada yang diubah)"); return
    from googleapiclient.errors import HttpError
    svc = build_service(RAHASIA / a.token)
    ok = 0
    for it in items:
        try:
            st = terapkan_satu(svc, it)
            if st == "ok": log(f"  OK {it['id']} | {(it.get('title') or '')[:60]}"); ok += 1
            else: log(f"  LEWAT {it['id']} ({st})")
        except HttpError as e:
            s = str(e)
            if "quota" in s.lower(): log("  KUOTA habis -> stop, lanjut besok."); break
            log(f"  GAGAL {it['id']}: {s[:160]}")
        except Exception as e:
            log(f"  ERROR {it['id']}: {str(e)[:160]}")
        time.sleep(1)
    log(f"Selesai: {ok}/{len(items)} ter-improve.")

if __name__ == "__main__":
    main()
