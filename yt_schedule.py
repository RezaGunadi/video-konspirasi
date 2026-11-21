# -*- coding: utf-8 -*-
"""Jadwalkan (publishAt) draft sains yang SUDAH diupload: long @07:00, short @17:00, mulai besok.
- Cluster dari rahasia/sains_clusters.json (long + short-nya). Urut cluster by upload terlama.
- Short di-SELING: round-robin per-rank (short-1 tiap topik dulu, baru short-2, dst) -> ga 3 hari berturut 1 topik.
- Set privacyStatus=private + publishAt (video jadi 'Dijadwalkan'). File tak disentuh.

  python yt_schedule.py --token yt_token.json --dry-run     # lihat jadwal (tanpa set)
  python yt_schedule.py --token yt_token.json               # SET publishAt
  python yt_schedule.py --token yt_token.json --start 2     # mulai 2 hari lagi
"""
import sys, json, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CFG = RAHASIA / "sains_clusters.json"
MANIFEST = RAHASIA / "yt_uploaded.json"
STUDY = RAHASIA / "yt_study_yt_token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
LOCAL_TZ = datetime.now().astimezone().tzinfo
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(t, flush=True)

def build_service(token_path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def titles():
    try: return {v["id"]: v["title"] for v in json.loads(STUDY.read_text(encoding="utf-8"))["videos"]}
    except Exception: return {}

def upload_time():
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return {v["video_id"]: v.get("uploaded_at", "") for v in man.values() if isinstance(v, dict) and v.get("video_id")}
    except Exception: return {}

def rencana(start_offset=1):
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    clusters = cfg["clusters"]; orphans = cfg.get("orphan_shorts", [])
    up = upload_time()
    clusters.sort(key=lambda c: up.get(c["long"], "9999"))   # upload terlama dulu
    base = (datetime.now(LOCAL_TZ) + timedelta(days=start_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    sched = []
    for d, c in enumerate(clusters):                          # LONG @07:00, 1/hari
        sched.append((c["long"], base.replace(hour=7) + timedelta(days=d), "LONG", c["topik"]))
    maxr = max([len(c["shorts"]) for c in clusters] + [0])
    order = []
    for r in range(maxr):                                     # SELING: short rank-0 semua topik dulu, lalu rank-1, dst
        for c in clusters:
            if r < len(c["shorts"]): order.append((c["shorts"][r], c["topik"]))
    order += [(s, "(short lepas)") for s in orphans]
    for s, (vid, topik) in enumerate(order):                  # SHORT @17:00, 1/hari
        sched.append((vid, base.replace(hour=17) + timedelta(days=s), "SHORT", topik))
    return sched

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="yt_token.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", type=int, default=1, help="mulai berapa hari lagi (default 1 = besok)")
    a = ap.parse_args()
    T = titles()
    sched = rencana(a.start)
    log(f"Total dijadwalkan: {len(sched)} ({sum(1 for x in sched if x[2]=='LONG')} long, {sum(1 for x in sched if x[2]=='SHORT')} short)")
    for vid, dt, kind, topik in sorted(sched, key=lambda x: x[1]):
        log(f"  {dt.strftime('%a %d %b %H:%M')} {kind:5} | {topik[:22]:22} | {T.get(vid, vid)[:46]}")
    if a.dry_run:
        log("(dry-run; belum di-set)"); return
    from googleapiclient.errors import HttpError
    svc = build_service(RAHASIA / a.token)
    ok = 0
    for vid, dt, kind, topik in sched:
        pub = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            svc.videos().update(part="status", body={"id": vid, "status": {
                "privacyStatus": "private", "publishAt": pub, "selfDeclaredMadeForKids": False}}).execute()
            ok += 1; log(f"  SET {kind:5} {dt.strftime('%d %b %H:%M')} | {T.get(vid, vid)[:40]}")
        except HttpError as e:
            s = str(e)
            if "quota" in s.lower(): log("  KUOTA habis -> lanjut besok."); break
            log(f"  GAGAL {vid}: {s[:140]}")
    log(f"Selesai: {ok}/{len(sched)} dijadwalkan.")

if __name__ == "__main__":
    main()
