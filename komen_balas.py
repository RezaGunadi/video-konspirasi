# -*- coding: utf-8 -*-
"""Auto-balas komentar video SAINS (publik, kampanye >= 2026-10-29).
- Skip komen yg SUDAH dibalas owner (cek balasan) & yg sudah tercatat di rahasia/komen_replied.json.
- Skip komen milik sendiri. Generate balasan natural via Ollama mini PC (persona Si Kepo).
- Post via comments().insert (50 unit/balas). Cap harian --max (default 25) biar hemat kuota.
  .venv\\Scripts\\python.exe komen_balas.py            # live, cap 25
  .venv\\Scripts\\python.exe komen_balas.py --dry       # preview tanpa post
  .venv\\Scripts\\python.exe komen_balas.py --max 40
"""
import sys, json, argparse, time, re
from pathlib import Path
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesin import config, ollama
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
ROOT = Path(__file__).resolve().parent; RAH = ROOT / "rahasia"
SC = ["https://www.googleapis.com/auth/youtube.force-ssl"]
STATE = RAH / "komen_replied.json"
KAMPANYE_SEJAK = "2026-10-29"   # awal kampanye sains (buang video lama non-sains)

PERSONA = (
    "Kamu 'Si Kepo', maskot channel edukasi sains berbahasa Indonesia yang ramah, hangat, dan penasaran. "
    "Balas komentar penonton dengan 1-2 kalimat singkat, natural, dan personal — seperti kreator asli, bukan bot. "
    "Kalau komennya pertanyaan, jawab singkat & akurat berbasis sains (jangan mengarang; kalau tak yakin, ajak penasaran). "
    "Kalau pujian, ucapkan terima kasih tulus. Kalau kritik, tanggapi sopan & terbuka. "
    "Pakai bahasa santai khas YouTube Indonesia, boleh 1 emoji yang pas. "
    "JANGAN menyebut dirimu AI, jangan menjanjikan hal berlebihan, jangan spam ajakan subscribe tiap balasan. "
    "Keluarkan HANYA teks balasan, tanpa tanda kutip, tanpa awalan nama."
)

def log(t): print(t, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25, help="maks balasan hari ini (hemat kuota)")
    ap.add_argument("--dry", action="store_true", help="preview, tidak post")
    ap.add_argument("--per-video", type=int, default=6, help="maks balasan per video")
    ap.add_argument("--ollama", default="", help="paksa host Ollama; kosong = auto mini PC di LAN")
    a = ap.parse_args()
    cfg = config.muat()
    # Ollama: laptop RAM-cekak -> pakai mini PC di LAN. Auto-pilih yg hidup.
    MINIPC = ["http://192.168.100.63:11434", "http://192.168.100.54:11434", "http://192.168.100.71:11434"]
    if a.ollama:
        cfg["ollama_url"] = a.ollama
    else:
        import requests
        for u in MINIPC:
            try:
                requests.get(u + "/api/tags", timeout=3); cfg["ollama_url"] = u; break
            except Exception:
                pass
    s = build("youtube", "v3", credentials=Credentials.from_authorized_user_file(str(RAH / "yt_token.json"), SC), cache_discovery=False)
    me = s.channels().list(part="id,contentDetails", mine=True).execute()["items"][0]
    my_id = me["id"]; up = me["contentDetails"]["relatedPlaylists"]["uploads"]
    log(f"Channel: {my_id} | Ollama: {cfg.get('ollama_url')} ({cfg.get('model')})")

    done = set(json.loads(STATE.read_text(encoding="utf-8"))) if STATE.exists() else set()

    # --- video sains publik (kampanye) ---
    ids = []; tok = None
    while True:
        r = s.playlistItems().list(part="contentDetails", playlistId=up, maxResults=50, pageToken=tok).execute()
        ids += [it["contentDetails"]["videoId"] for it in r["items"]]; tok = r.get("nextPageToken")
        if not tok: break
    vids = {}
    for i in range(0, len(ids), 50):
        r = s.videos().list(part="snippet,status", id=",".join(ids[i:i+50])).execute()
        for v in r["items"]:
            if v["status"].get("privacyStatus") == "public" and v["snippet"].get("publishedAt", "")[:10] >= KAMPANYE_SEJAK:
                vids[v["id"]] = v["snippet"]["title"]
    log(f"Video sains publik dipantau: {len(vids)}")

    posted = 0
    for vid, judul in sorted(vids.items(), key=lambda kv: kv[1]):
        if posted >= a.max: break
        try:
            r = s.commentThreads().list(part="snippet,replies", videoId=vid, maxResults=100,
                                        order="time", textFormat="plainText").execute()
        except HttpError as e:
            if "disabled comments" in str(e).lower() or "commentsDisabled" in str(e): continue
            log(f"  (gagal list komen {vid}: {str(e)[:70]})"); continue
        per_vid = 0
        for t in r.get("items", []):
            if posted >= a.max or per_vid >= a.per_video: break
            top = t["snippet"]["topLevelComment"]
            cid = top["id"]; ts = top["snippet"]
            aid = ts.get("authorChannelId", {}).get("value", "")
            if aid == my_id: continue                      # komen sendiri
            if cid in done: continue                       # sudah pernah dibalas (tercatat)
            # sudah dibalas owner?
            replied_by_me = any(rep["snippet"].get("authorChannelId", {}).get("value", "") == my_id
                                for rep in t.get("replies", {}).get("comments", []))
            if replied_by_me:
                done.add(cid); continue
            teks = ts["textOriginal"].strip()
            if len(teks) < 2: continue
            # generate balasan
            try:
                pesan = [{"role": "system", "content": PERSONA},
                         {"role": "user", "content": f"Judul video: {judul}\nKomentar penonton (@{ts['authorDisplayName']}): {teks}\n\nBalasanmu:"}]
                balas = ollama.chat(cfg, pesan, suhu=0.7, maks_token=120).strip()
                balas = re.sub(r'^["\']|["\']$', "", balas).strip()[:380]
            except Exception as e:
                log(f"  (ollama gagal: {str(e)[:70]})"); continue
            if not balas: continue
            log(f"\n  VID {vid[:11]} | {judul[:40]}")
            log(f"   @{ts['authorDisplayName']}: {teks[:80]}")
            log(f"   -> {balas}")
            if not a.dry:
                try:
                    s.comments().insert(part="snippet", body={"snippet": {"parentId": cid, "textOriginal": balas}}).execute()
                    done.add(cid); posted += 1; per_vid += 1; time.sleep(0.5)
                except HttpError as e:
                    if "quota" in str(e).lower(): log("  KUOTA habis, stop."); STATE.write_text(json.dumps(sorted(done)), encoding="utf-8"); return
                    log(f"   GAGAL post: {str(e)[:80]}")
            else:
                per_vid += 1; posted += 1
    STATE.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    log(f"\n{'[DRY] ' if a.dry else ''}Selesai: {posted} balasan{' (preview)' if a.dry else ' terkirim'}. Total tercatat: {len(done)}.")

if __name__ == "__main__":
    main()
