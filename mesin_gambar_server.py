# -*- coding: utf-8 -*-
"""Server gambar AI LOKAL untuk fallback footage. Jalan di LAPTOP ber-GPU (pakai sdenv), dipanggil mini PC
(tanpa GPU) lewat HTTP LAN. Di tiap mini PC set config 'gen_url' = http://<ip-laptop>:7870 .

  sdenv\\Scripts\\python.exe mesin_gambar_server.py --warm
  sdenv\\Scripts\\python.exe mesin_gambar_server.py --port 7870 --model Lykon/dreamshaper-8 --steps 20

Endpoint:
  GET /gen?prompt=<teks>&w=1080&h=1920&seed=123   -> image/jpeg
  GET /health                                      -> "ok"

Satu GPU -> semua permintaan di-serialize (Lock); pipeline dimuat sekali. GTX 16xx: fp32 + VAE upcast
(fp16 -> gambar hitam/NaN). Render di resolusi kecil (hemat VRAM 4GB) lalu cover-crop ke w x h.

CATATAN KECEPATAN: dreamshaper-8 fp32 di GPU 4GB ~ beberapa menit/gambar. Kalau kebanyakan, ganti
--model stabilityai/sd-turbo --steps 2 (jauh lebih cepat, kualitas b-roll cukup). _unduh_gen di footage.py
sudah pakai timeout longgar (900 dtk) jadi aman walau lambat.
"""
import argparse, io, sys, threading, time
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from PIL import Image

NEG = ("text, watermark, logo, caption, blurry, low quality, deformed, split image, collage, "
       "frame, border, nsfw")

_PIPE = None
_LOCK = threading.Lock()
ARGS = None


def pipe():
    global _PIPE
    if _PIPE is None:
        from diffusers import StableDiffusionPipeline
        print("load SD:", ARGS.model, flush=True)
        p = StableDiffusionPipeline.from_pretrained(
            ARGS.model, torch_dtype=torch.float32, safety_checker=None, requires_safety_checker=False)
        p = p.to("cuda")
        p.vae.config.force_upcast = True          # GTX 16xx: VAE fp16 -> hitam; upcast fp32 saat decode
        p.enable_attention_slicing()
        try: p.vae.enable_slicing()
        except Exception: pass
        p.set_progress_bar_config(disable=True)
        _PIPE = p
        print("SD ready.", flush=True)
    return _PIPE


def _b8(n):
    return max(256, (int(n) // 8) * 8)


def gen(prompt, w, h, seed):
    ar = w / h
    base = 640
    if ar >= 1:
        gw, gh = base, base / ar
    else:
        gw, gh = base * ar, base
    g = torch.Generator("cuda").manual_seed(int(seed) % (2 ** 31))
    img = pipe()(prompt, negative_prompt=NEG, num_inference_steps=ARGS.steps,
                 guidance_scale=6.5, width=_b8(gw), height=_b8(gh), generator=g).images[0]
    s = max(w / img.width, h / img.height)        # cover-crop ke rasio minta
    img = img.resize((max(w, int(img.width * s)), max(h, int(img.height * s))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    img = img.crop((x, y, x + w, y + h))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        if u.path != "/gen":
            self.send_response(404); self.end_headers(); return
        prompt = (q.get("prompt", [""])[0]).strip()
        if len(prompt) < 4:
            self.send_response(400); self.end_headers(); return
        w = max(256, min(1920, int(q.get("w", ["1080"])[0] or 1080)))
        h = max(256, min(1920, int(q.get("h", ["1920"])[0] or 1920)))
        seed = int(q.get("seed", ["0"])[0] or 0)
        t0 = time.time()
        try:
            with _LOCK:                            # satu GPU -> antre
                data = gen(prompt, w, h, seed)
        except Exception as e:
            print("GAGAL:", repr(e)[:160], flush=True)
            try: self.send_response(500); self.end_headers()
            except Exception: pass
            return
        print(f"OK {int(time.time()-t0)}s {w}x{h} :: {prompt[:60]}", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7870)
    ap.add_argument("--model", default="Lykon/dreamshaper-8")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--warm", action="store_true", help="muat SD saat start (bukan saat request pertama)")
    ARGS = ap.parse_args()
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    if ARGS.warm:
        pipe()
    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), H)
    print(f"server gambar AI: http://{ARGS.host}:{ARGS.port}  (model {ARGS.model}, steps {ARGS.steps})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
