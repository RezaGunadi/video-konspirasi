# -*- coding: utf-8 -*-
"""Pelajari channel: tarik SEMUA video + judul/deskripsi/tags/status/views/thumbnail via API (baca saja).
Dump ke rahasia/yt_study_<token>.json (lengkap) + print ringkasan. Dipakai buat analisis style sebelum improve.

  python yt_study.py --token yt_token.json
"""
import sys, json, time, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(t, flush=True)

def build_service(token_path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def studi(token_path):
    svc = build_service(token_path)
    ch = svc.channels().list(part="contentDetails,snippet,statistics", mine=True).execute()["items"][0]
    name = ch["snippet"]["title"]; subs = ch.get("statistics", {}).get("subscriberCount", "?")
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = svc.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok).execute()
        ids += [it["contentDetails"]["videoId"] for it in r["items"]]
        tok = r.get("nextPageToken")
        if not tok: break
    rows = []
    for i in range(0, len(ids), 50):
        r = svc.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(ids[i:i+50])).execute()
        for v in r["items"]:
            s = v["snippet"]; st = v["status"]; stat = v.get("statistics", {}); th = s.get("thumbnails", {})
            rows.append({
                "id": v["id"], "title": s.get("title", ""), "privacy": st.get("privacyStatus"),
                "publishAt": st.get("publishAt"), "views": int(stat.get("viewCount", 0) or 0),
                "likes": int(stat.get("likeCount", 0) or 0), "comments": int(stat.get("commentCount", 0) or 0),
                "tags": s.get("tags", []), "desc": s.get("description", ""),
                "custom_thumb": ("maxres" in th or "standard" in th),
                "thumb": (th.get("maxres") or th.get("high") or th.get("default") or {}).get("url", ""),
                "dur": v.get("contentDetails", {}).get("duration", ""),
            })
    rows.sort(key=lambda x: -x["views"])
    outp = RAHASIA / f"yt_study_{token_path.stem}.json"
    outp.write_text(json.dumps({"channel": name, "subs": subs, "videos": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    pub = [r for r in rows if r["privacy"] == "public"]
    drafts = [r for r in rows if r["privacy"] != "public"]
    log(f"CHANNEL: {name} (subs {subs}) | total video: {len(rows)} | PUBLIK: {len(pub)} | draft/private/scheduled: {len(drafts)}")
    log(f"dump lengkap -> {outp}")
    cust = sum(1 for r in rows if r["custom_thumb"])
    log(f"custom thumbnail: {cust}/{len(rows)} | tags kosong: {sum(1 for r in rows if not r['tags'])} | desc kosong: {sum(1 for r in rows if not r['desc'].strip())}")
    log("\n--- TOP 8 PUBLIK (by views) — patokan kualitas ---")
    for r in pub[:8]:
        log(f"  {r['views']:>6}x | tags {len(r['tags']):>2} | desc {len(r['desc']):>4}c | thumb {'Y' if r['custom_thumb'] else 'n'} | {r['title'][:70]}")
    log("\n--- DRAFT/PRIVATE (yang mau di-improve) ---")
    for r in drafts[:25]:
        log(f"  [{r['privacy'][:4]}] tags {len(r['tags']):>2} | desc {len(r['desc']):>4}c | thumb {'Y' if r['custom_thumb'] else 'n'} | {r['title'][:66]}")
    if len(drafts) > 25: log(f"  ...(+{len(drafts)-25} lagi)")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--token", default="yt_token.json")
    a = ap.parse_args()
    studi(RAHASIA / a.token)

if __name__ == "__main__":
    main()
