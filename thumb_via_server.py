# -*- coding: utf-8 -*-
"""Generate thumbnail SHORT lewat SERVER SD (http://127.0.0.1:7870/gen) — tanpa load pipeline kedua,
antre bareng footage di 1 GPU (server pakai _LOCK). Overlay teks pakai fungsi sd_thumb.
Hanya proses entri fmt 9:16 yg file thumb2-nya BELUM ada (27 teaser sisa). Jalankan dgn sdenv python.
  sdenv\\Scripts\\python.exe thumb_via_server.py
"""
import sys, json, io, time, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sd_thumb import overlay, STYLE, DIMS, OUTDIR, CFG
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
SRV = "http://127.0.0.1:7870/gen"

def ambil(prompt, w, h, seed, timeout=1200):
    url = SRV + "?" + urllib.parse.urlencode({"prompt": prompt, "w": w, "h": h, "seed": seed})
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")

def main():
    items = json.loads(CFG.read_text(encoding="utf-8"))
    todo = [it for it in items if it.get("fmt") == "9:16" and not (OUTDIR / f"{it['id']}.jpg").exists()]
    print(f"Thumbnail lewat server: {len(todo)} perlu dibuat.", flush=True)
    ok = 0
    for i, it in enumerate(todo, 1):
        vid = it["id"]; w, h, gw, gh = DIMS["9:16"]
        prompt = (it.get("query") or it["hook"]) + STYLE
        t0 = time.time()
        try:
            bg = ambil(prompt, w, h, seed=(abs(hash(vid)) % 1000))
            overlay(bg, it["hook"], OUTDIR / f"{vid}.jpg", w, h)
            ok += 1
            print(f"[{i}/{len(todo)}] {vid} ({int(time.time()-t0)}s) -> {it['hook']}", flush=True)
        except Exception as e:
            print(f"[{i}/{len(todo)}] {vid} GAGAL: {str(e)[:100]}", flush=True)
    print(f"SELESAI: {ok}/{len(todo)} thumbnail dibuat. Lalu jalankan set_thumbs.py buat pasang.", flush=True)

if __name__ == "__main__":
    main()
