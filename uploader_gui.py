# -*- coding: utf-8 -*-
"""Panel kontrol upload YouTube — GUI web lokal, gampang di-run & disuruh.
- Ga butuh Flask/instalasi apa pun (pakai http.server stdlib).
- Tiap aksi (auth / cek channel / preview antrean / upload) = spawn uploader pakai .venv python.
- Multi-channel: tiap channel punya token sendiri (yt_token*.json). Tombol "Auth" = buka browser buat
  consent SEKALI per akun (langkah yg emang wajib kamu klik sendiri).

Jalanin:  & "d:\\smart ai\\video-konspirasi\\.venv\\Scripts\\python.exe" "d:\\smart ai\\video-konspirasi\\uploader_gui.py"
Lalu buka:  http://127.0.0.1:3301
"""
import json, subprocess, threading, time, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
LOGDIR = RAHASIA / "gui_logs"; LOGDIR.mkdir(parents=True, exist_ok=True)
VENV = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(VENV) if VENV.exists() else sys.executable
PORT = 3301

# Daftar channel. Tambah channel baru = tambah entri di sini (token file beda = channel beda).
CH = {
    "sains":   {"label": "Reza Al Fath — Sains (auto drip)", "script": "yt_upload.py", "token": "yt_token.json",
                "drip": True, "base": [],
                "note": "Auto-upload 6/hari. Jadwal/public jalan setelah audit lolos (AUDITED=True)."},
    "kelasprivat": {"label": "KelasPrivat — Tutorial (PRIVATE)", "script": "yt_folder.py", "token": "yt_token_kp.json",
                "drip": True, "playlist": True, "base": ["--token", "yt_token_kp.json", "--dir", r"E:\Tutorial Ujian KelasPrivat"],
                "note": "Upload PRIVATE: video lengkap + per bagian (skip folder _*). File sumber TIDAK dihapus."},
    "kuliner": {"label": "Keluarga Halal Explorer (optimasi)", "script": "yt_apply.py", "token": "yt_token_khe.json",
                "drip": False, "base": [],
                "note": "Upload manual; GUI dipakai buat auth + cek channel. Metadata via yt_apply."},
}

jobs = {}   # ch -> {"proc": Popen, "log": Path, "action": str}

def logpath(ch): return LOGDIR / f"{ch}.log"

def build_args(ch, action, limit):
    c = CH[ch]; base = [PY, str(ROOT / c["script"])] + c.get("base", [])
    lim = (["--limit", str(limit)] if limit else [])
    if action == "auth":    return base + ["--auth"]
    if action == "whoami":  return base + ["--whoami"]
    if action == "preview":
        if c["script"] in ("yt_upload.py", "yt_folder.py"):
            return base + ["--dry-run"] + lim
        return base + ["--whoami"]
    if action == "upload" and c.get("drip"):
        return base + lim
    if action == "playlist" and c.get("playlist"):
        return base + ["--playlist"]
    return None

def start_job(ch, action, limit):
    if ch in jobs and jobs[ch]["proc"].poll() is None:
        return False, "Masih ada proses jalan buat channel ini — tunggu / refresh log."
    args = build_args(ch, action, limit)
    if not args:
        return False, "Aksi ga valid buat channel ini."
    lp = logpath(ch)
    f = open(lp, "w", encoding="utf-8")
    f.write(f"$ {' '.join(args)}\n(mulai {time.strftime('%H:%M:%S')})\n")
    f.flush()
    env = None
    try:
        proc = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, cwd=str(ROOT),
                                env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"})
    except Exception as e:
        f.write(f"GAGAL start: {e}\n"); f.close()
        return False, str(e)
    jobs[ch] = {"proc": proc, "log": lp, "action": action, "f": f}
    return True, "mulai"

def status():
    out = []
    for key, c in CH.items():
        j = jobs.get(key)
        running = bool(j and j["proc"].poll() is None)
        out.append({
            "key": key, "label": c["label"], "drip": c.get("drip", False), "note": c.get("note", ""),
            "playlist": c.get("playlist", False),
            "authed": (RAHASIA / c["token"]).exists(),
            "running": running, "last_action": (j or {}).get("action", ""),
        })
    return out

def tail(ch, n=120):
    lp = logpath(ch)
    if not lp.exists(): return ""
    try:
        lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(ga bisa baca log: {e})"

PAGE = """<!doctype html><html lang=id><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Panel Upload</title>
<style>
:root{color-scheme:dark}
body{font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
header{padding:16px 20px;border-bottom:1px solid #232733;background:#141821}
h1{font-size:18px;margin:0}
.wrap{max-width:900px;margin:0 auto;padding:18px}
.card{background:#161b24;border:1px solid #242a36;border-radius:12px;padding:16px;margin:14px 0}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.lbl{font-weight:600;font-size:16px}
.badge{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid #39506b}
.ok{color:#7ee081;border-color:#2f6b36}.no{color:#ff9a9a;border-color:#6b2f2f}
.run{color:#ffd27a;border-color:#6b5a2f}
button{background:#2b6cff;color:#fff;border:0;border-radius:8px;padding:7px 12px;font-size:14px;cursor:pointer}
button.sec{background:#2a2f3a}button:disabled{opacity:.5;cursor:default}
input{width:64px;background:#0f141c;border:1px solid #2a2f3a;color:#e6e6e6;border-radius:6px;padding:6px}
.note{color:#9aa4b2;font-size:13px;margin:6px 0 10px}
pre{background:#0b0e13;border:1px solid #1e2430;border-radius:8px;padding:10px;max-height:240px;overflow:auto;white-space:pre-wrap;font-size:12.5px}
small{color:#9aa4b2}
</style></head><body>
<header><div class=wrap style=padding:0><h1>🎬 Panel Upload YouTube</h1>
<small>Lokal • http://127.0.0.1:3301 • auth = 1 klik consent per akun</small></div></header>
<div class=wrap id=app>memuat…</div>
<script>
async function j(u,o){const r=await fetch(u,o);return r.json()}
function card(c){
 const a=c.authed?'<span class="badge ok">ter-auth</span>':'<span class="badge no">belum auth</span>';
 const r=c.running?'<span class="badge run">jalan…</span>':'';
 const lim=c.drip?`<input id=lim_${c.key} type=number value=6 min=1 max=50 title="jumlah video">`:'';
 const up=c.drip?`<button onclick="run('${c.key}','upload')">⬆ Upload ${lim}</button>
   <button class=sec onclick="run('${c.key}','preview')">👁 Preview antrean</button>`:'';
 const pl=c.playlist?`<button class=sec onclick="run('${c.key}','playlist')">📋 Buat Playlist</button>`:'';
 return `<div class=card>
   <div class=row><span class=lbl>${c.label}</span> ${a} ${r}</div>
   <div class=note>${c.note||''}</div>
   <div class=row>
     <button onclick="run('${c.key}','auth')">🔑 Auth (buka browser)</button>
     <button class=sec onclick="run('${c.key}','whoami')">✔ Cek channel</button>
     ${up}
   </div>
   <pre id=log_${c.key}><small>— log —</small></pre>
 </div>`;
}
async function load(){const s=await j('/api/status');document.getElementById('app').innerHTML=s.map(card).join('');s.forEach(c=>poll(c.key))}
async function run(ch,action){
 const lim=(document.getElementById('lim_'+ch)||{}).value||'';
 await j('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ch,action,limit:lim})});
 setTimeout(()=>load(),400); poll(ch);
}
const timers={};
async function poll(ch){
 clearInterval(timers[ch]);
 timers[ch]=setInterval(async()=>{
   const d=await j('/api/log?ch='+ch);
   const el=document.getElementById('log_'+ch); if(el){el.textContent=d.log||'(kosong)';el.scrollTop=el.scrollHeight}
   if(!d.running){clearInterval(timers[ch])}
 },1500);
}
load();
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/status":
            return self._send(200, json.dumps(status()))
        if u.path == "/api/log":
            ch = (parse_qs(u.query).get("ch") or [""])[0]
            running = bool(ch in jobs and jobs[ch]["proc"].poll() is None)
            return self._send(200, json.dumps({"log": tail(ch), "running": running}))
        return self._send(404, json.dumps({"err": "not found"}))
    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/run":
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            ch = body.get("ch"); action = body.get("action"); limit = body.get("limit") or ""
            if ch not in CH:
                return self._send(400, json.dumps({"ok": False, "msg": "channel ga dikenal"}))
            ok, msg = start_job(ch, action, str(limit))
            return self._send(200, json.dumps({"ok": ok, "msg": msg}))
        return self._send(404, json.dumps({"err": "not found"}))

def main():
    print(f"Panel upload jalan di http://127.0.0.1:{PORT}  (python: {PY})")
    print("Buka di browser. Ctrl+C buat berhenti.")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

if __name__ == "__main__":
    main()
