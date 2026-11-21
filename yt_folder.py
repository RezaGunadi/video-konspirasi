# -*- coding: utf-8 -*-
"""Uploader folder generik: upload semua video dalam satu folder ke 1 channel YouTube (default PRIVATE).
- SKIP subfolder yang diawali '_' (folder kerja/arsip/latihan).
- File sumber TIDAK pernah dihapus (ini master punya user).
- Dedup via manifest per-token (idempoten). Judul diambil dari nama file.
- Channel ditentukan oleh --token (tiap channel = token sendiri). OAuth client dipakai bareng (rahasia/yt_client.json).

Pakai:
  python yt_folder.py --token yt_token_kp.json --auth                                   # sekali: login, PILIH channel
  python yt_folder.py --token yt_token_kp.json --whoami
  python yt_folder.py --token yt_token_kp.json --dir "E:\\Tutorial Ujian KelasPrivat" --dry-run
  python yt_folder.py --token yt_token_kp.json --dir "E:\\Tutorial Ujian KelasPrivat" --limit 5
"""
import os, re, sys, json, time, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CLIENT = RAHASIA / "yt_client.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
VID = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
CATEGORY = "27"          # Education
PRIVACY = "private"
TITLE_MAX = 100

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(time.strftime("%H:%M:%S"), t, flush=True)

def load_json(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d
def save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(p)

def manifest_path(token): return RAHASIA / (Path(token).stem + "_folder_manifest.json")

def get_creds(token_path, interactive):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid: return creds
    if creds and creds.expired and creds.refresh_token:
        try: creds.refresh(Request()); save_json(token_path, json.loads(creds.to_json())); return creds
        except Exception as e: log(f"refresh token gagal ({e}); perlu --auth ulang")
    if not interactive:
        raise SystemExit(f"Belum ada token sah ({token_path.name}). Jalankan: python yt_folder.py --token {token_path.name} --auth")
    if not CLIENT.exists(): raise SystemExit(f"Taruh OAuth client di: {CLIENT}")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    save_json(token_path, json.loads(creds.to_json())); log(f"token tersimpan -> {token_path}")
    return creds

def build_service(token_path, interactive=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=get_creds(token_path, interactive), cache_discovery=False)

def whoami(svc):
    r = svc.channels().list(part="snippet,statistics", mine=True).execute()
    its = r.get("items", [])
    if not its: log("Token sah tapi tanpa channel?"); return None
    c = its[0]; log(f"CHANNEL: {c['snippet']['title']}  (id {c['id']}, subs {c.get('statistics',{}).get('subscriberCount','?')})")
    return c["snippet"]["title"]

def kumpulkan(root):
    """Semua video di root, KECUALI yang ada di subfolder diawali '_'. Urut: '1 Video Lengkap' dulu, lalu per-bagian."""
    root = Path(root); items = []
    if not root.exists(): raise SystemExit(f"Folder ga ada: {root}")
    for p in root.rglob("*"):
        if p.is_dir() or p.suffix.lower() not in VID: continue
        rel = p.relative_to(root)
        if any(part.startswith("_") for part in rel.parts): continue
        items.append((str(rel), p))
    items.sort(key=lambda x: x[0].lower())
    return items

def judul_dari(p):
    return (re.sub(r"\s+", " ", p.stem).strip().replace("<", "").replace(">", "")[:TITLE_MAX]) or "Video"

def upload_satu(svc, p, rel):
    from googleapiclient.http import MediaFileUpload
    title = judul_dari(p)
    desc = f"Tutorial KelasPrivat — {Path(rel).parent.as_posix()}".replace("<", "(").replace(">", ")")
    body = {"snippet": {"title": title, "description": desc, "categoryId": CATEGORY,
                        "defaultLanguage": "id", "defaultAudioLanguage": "id"},
            "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False, "embeddable": True}}
    media = MediaFileUpload(str(p), chunksize=8 * 1024 * 1024, resumable=True)
    req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None; last = 0
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            pct = int(st.progress() * 100)
            if pct >= last + 25: log(f"    ...{pct}%"); last = pct
    return resp["id"], title

def run(token_path, root, limit):
    from googleapiclient.errors import HttpError
    svc = build_service(token_path, False)
    nama = whoami(svc)
    if not nama: return
    man = load_json(manifest_path(token_path), {})
    items = [(rel, p) for rel, p in kumpulkan(root) if rel not in man]
    if not items: log("Semua video udah keupload. Selesai."); return
    n = min(limit or len(items), len(items))
    log(f"Antre {len(items)} video (channel {nama}); upload {n} run ini — PRIVATE, file sumber aman.")
    ok = 0
    for rel, p in items[:n]:
        log(f"  upload: {rel}")
        try:
            vid, title = upload_satu(svc, p, rel)
        except HttpError as e:
            s = str(e)
            if "quotaExceeded" in s or "uploadLimitExceeded" in s or "dailyLimitExceeded" in s:
                log("KUOTA HARIAN HABIS -> berhenti rapi, lanjut besok (yg sukses sudah di-flag)."); break
            log(f"  GAGAL (skip) {rel}: {s[:140]}"); continue
        except Exception as e:
            log(f"  ERROR (skip) {rel}: {str(e)[:140]}"); continue
        man[rel] = {"video_id": vid, "title": title, "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        save_json(manifest_path(token_path), man); ok += 1; time.sleep(1)
    log(f"Selesai run: {ok} terupload. Sisa antre ~{len(items) - ok}.")

def dry_run(token_path, root, limit):
    items = kumpulkan(root); man = load_json(manifest_path(token_path), {})
    sisa = [(rel, p) for rel, p in items if rel not in man]
    log(f"Video (lengkap + per bagian, skip folder _*): {len(items)} | udah upload: {len(man)} | sisa: {len(sisa)}")
    for rel, p in sisa[:(limit or 20)]:
        log(f"  [ANTRE] {rel}  -> judul: {judul_dari(p)}")
    log("(dry-run; tidak ada yang diupload)")

def _playlists_man(token_path): return RAHASIA / (Path(token_path).stem + "_playlists.json")

def grup_playlist(man):
    """Kelompokkan video keupload per FOLDER induk, urut nama (01, 02, ... -> 01 di atas)."""
    groups = {}
    for rel, info in man.items():
        parent = Path(rel).parent.as_posix()
        groups.setdefault(parent, []).append((rel, info["video_id"]))
    for g in groups.values(): g.sort(key=lambda x: x[0].lower())
    return groups

def buat_playlist(token_path, root, hanya_segmen=False):
    """Buat/isi playlist per folder dari video yang SUDAH keupload (manifest), urut awal->akhir.
    hanya_segmen=True -> lewati folder '1 Video Lengkap' (cuma per-bagian)."""
    from googleapiclient.errors import HttpError
    svc = build_service(token_path, False)
    if not whoami(svc): return
    man = load_json(manifest_path(token_path), {})
    if not man: log("Belum ada video keupload; playlist nanti setelah upload."); return
    pman = load_json(_playlists_man(token_path), {})
    for folder, vids in grup_playlist(man).items():
        if hanya_segmen and folder.lower().startswith("1 "): continue
        title = "KelasPrivat — " + folder.replace("/", " / ")
        entry = pman.get(folder) or {"items": {}}
        pid = entry.get("playlist_id")
        if not pid:
            try:
                r = svc.playlists().insert(part="snippet,status", body={
                    "snippet": {"title": title[:150], "description": f"Tutorial KelasPrivat — {folder} (urut awal→akhir)"},
                    "status": {"privacyStatus": "public"}}).execute()
                pid = r["id"]; entry = {"playlist_id": pid, "items": {}}
                log(f"  playlist dibuat: {title} ({pid})")
            except HttpError as e:
                log(f"  GAGAL buat playlist {title}: {str(e)[:120]}"); continue
        entry.setdefault("items", {})
        for rel, vid in vids:                       # urut: awal di atas
            if entry["items"].get(rel): continue
            try:
                svc.playlistItems().insert(part="snippet", body={"snippet": {
                    "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
                entry["items"][rel] = True; log(f"    + {rel}")
            except HttpError as e:
                s = str(e)
                if "quota" in s.lower() or "dailyLimit" in s:
                    log("  KUOTA habis saat isi playlist -> lanjut besok.")
                    pman[folder] = entry; save_json(_playlists_man(token_path), pman); return
                log(f"    GAGAL tambah {rel}: {s[:100]}")
        pman[folder] = entry; save_json(_playlists_man(token_path), pman)
    log("Playlist selesai (urut per folder).")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="yt_token.json", help="nama file token di rahasia/ (channel)")
    ap.add_argument("--dir", help="folder sumber video")
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--whoami", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--playlist", action="store_true", help="buat/isi playlist per folder (urut) dari video yg sudah keupload")
    ap.add_argument("--segmen-only", action="store_true", help="playlist cuma folder per-bagian (lewati '1 Video Lengkap')")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    RAHASIA.mkdir(parents=True, exist_ok=True)
    tp = RAHASIA / a.token
    if a.auth: whoami(build_service(tp, True)); return
    if a.whoami: whoami(build_service(tp, False)); return
    if a.playlist:
        if not a.dir: raise SystemExit("Butuh --dir <folder>")
        buat_playlist(tp, a.dir, hanya_segmen=a.segmen_only); return
    if not a.dir: raise SystemExit("Butuh --dir <folder>")
    if a.dry_run: dry_run(tp, a.dir, a.limit); return
    run(tp, a.dir, a.limit)

if __name__ == "__main__":
    main()
