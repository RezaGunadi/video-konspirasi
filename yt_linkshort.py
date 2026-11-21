# -*- coding: utf-8 -*-
"""Tambahkan link VIDEO PANJANG ke deskripsi tiap SHORT (dari rahasia/sains_clusters.json).
Short orphan (tanpa long di scope) dilewati.  python yt_linkshort.py --token yt_token.json"""
import sys, json, argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CFG = RAHASIA / "sains_clusters.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(t, flush=True)

def build_service(tp):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    c = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if c.expired and c.refresh_token: c.refresh(Request()); tp.write_text(c.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=c, cache_discovery=False)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--token", default="yt_token.json"); a = ap.parse_args()
    svc = build_service(RAHASIA / a.token)
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    n = 0
    for c in cfg["clusters"]:
        link = f"https://youtu.be/{c['long']}"
        for sid in c.get("shorts", []):
            try:
                sn = svc.videos().list(part="snippet", id=sid).execute()["items"][0]["snippet"]
                desc = sn.get("description", "")
                if link in desc: log(f"  (udah ada) {sid}"); continue
                new = (desc.rstrip() + f"\n\n▶ Tonton VIDEO LENGKAP-nya di sini:\n{link}")[:4900]
                body = {"id": sid, "snippet": {"title": sn.get("title") or "Video", "description": new,
                        "tags": sn.get("tags", []), "categoryId": sn.get("categoryId", "27")}}
                for k in ("defaultLanguage", "defaultAudioLanguage"):
                    if sn.get(k): body["snippet"][k] = sn[k]
                svc.videos().update(part="snippet", body=body).execute()
                log(f"  LINK {sid} -> {c['long']} ({c['topik']})"); n += 1
            except Exception as e:
                log(f"  GAGAL {sid}: {str(e)[:120]}")
    log(f"Selesai: {n} short dikasih link ke video panjang.")

if __name__ == "__main__":
    main()
