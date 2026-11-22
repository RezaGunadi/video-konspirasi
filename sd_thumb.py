# -*- coding: utf-8 -*-
"""Generate thumbnail background pakai SD LOKAL (GPU, gratis, no-key) + overlay teks hook bold.
Format-aware: LONG -> 16:9 (1280x720), SHORT -> 9:16 (720x1280). Ambil 'fmt' per-entri config.
JALANKAN dengan sdenv python (ada torch-CUDA + diffusers):
  sdenv\\Scripts\\python.exe sd_thumb.py --test                 # 1 gambar uji
  sdenv\\Scripts\\python.exe sd_thumb.py --ids a,b,c            # regen id tertentu saja
  sdenv\\Scripts\\python.exe sd_thumb.py                        # semua -> rahasia/thumb2/<id>.jpg
Config: rahasia/sains_thumbs.json [{id, hook, query, emoji, fmt}]. Set thumbnail-nya via set_thumbs.py (venv).
"""
import json, sys, time, argparse
from pathlib import Path
import torch
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CFG = RAHASIA / "sains_thumbs.json"
OUTDIR = RAHASIA / "thumb2"; OUTDIR.mkdir(parents=True, exist_ok=True)
# fmt -> (W, H, GW, GH): render res kecil (fp32 di 4GB), lalu cover-crop/upscale ke ukuran final.
DIMS = {"16:9": (1280, 720, 576, 384), "9:16": (720, 1280, 384, 672)}
STYLE = ", dramatic cinematic lighting, bold vivid colors, high contrast, highly detailed, photorealistic, epic, 8k"
NEG = "text, watermark, logo, caption, blurry, low quality, deformed, split image, collage, frame, border"
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(t, flush=True)

_PIPE = None
def pipe():
    global _PIPE
    if _PIPE is None:
        from diffusers import StableDiffusionPipeline
        log("load SD (dreamshaper-8)…")
        # fp32: GTX 16xx menghasilkan NaN/hitam di fp16 (bahkan dgn VAE upcast) -> wajib fp32. Lambat tapi benar.
        p = StableDiffusionPipeline.from_pretrained(
            "Lykon/dreamshaper-8", torch_dtype=torch.float32, safety_checker=None, requires_safety_checker=False)
        p = p.to("cuda")
        p.vae.config.force_upcast = True      # GTX 16xx: fp16 VAE -> hitam/NaN; upcast fp32 saat decode
        p.enable_attention_slicing()
        try: p.vae.enable_slicing()
        except Exception: pass
        p.set_progress_bar_config(disable=True)
        _PIPE = p; log("SD ready.")
    return _PIPE

def gen_bg(query, gw, gh, w, h):
    img = pipe()(query + STYLE, negative_prompt=NEG,
                 num_inference_steps=24, guidance_scale=6.5, width=gw, height=gh).images[0]
    s = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(img.width * s)), max(h, int(img.height * s))))
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))

def impact(sz):
    for p in (r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if Path(p).exists(): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def _wrap(d, text, maxw, f):
    words = text.upper().split(); lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw: cur = t
        else:
            if cur: lines.append(cur); cur = w
            else: lines.append(w); cur = ""   # satu kata > maxw (langka): biarkan, tak dipaksa jadi 1 baris semua
    if cur: lines.append(cur)
    return lines

def _fit(d, text, maxw, maxh, start):
    """Selalu WRAP; turunkan ukuran sampai muat. Tak pernah balikin 1 baris tak-wrap (anti kepotong)."""
    s = start
    while s >= 34:
        f = impact(s); lines = _wrap(d, text, maxw, f); lh = int(s * 1.03)
        maxlines = 3 if s > 46 else 4
        if len(lines) <= maxlines and lh * len(lines) <= maxh and all(d.textlength(l, font=f) <= maxw for l in lines):
            return f, lines, lh
        s -= 4
    f = impact(34)                             # fallback: tetap wrap di ukuran terkecil (bukan 1 baris overflow)
    return f, _wrap(d, text, maxw, f), int(34 * 1.03)

def overlay(bg, hook, out, w, h):
    img = ImageEnhance.Contrast(bg).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.12)
    # gelap di bawah biar teks kebaca. Short (tinggi) -> mulai lebih bawah.
    mulai = 0.52 if h > w else 0.40
    grad = Image.new("L", (1, h), 0)
    for yy in range(h): grad.putpixel((0, yy), int(245 * max(0, (yy - h * mulai) / (h * (1 - mulai))) ** 1.25))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, grad.resize((w, h)))
    d = ImageDraw.Draw(img)
    start = int(w * 0.14)                       # ukuran font awal relatif lebar
    # margin samping 6% kiri+kanan (was 4%) -> aman dari crop player short & tak kepotong
    f, lines, lh = _fit(d, hook, w - int(w * 0.12), h * 0.42, start)
    y0 = h - lh * len(lines) - int(h * 0.06)
    for i, ln in enumerate(lines):
        x = (w - d.textlength(ln, font=f)) // 2
        d.text((x, y0 + i * lh), ln, font=f, fill=(255, 232, 0),
               stroke_width=max(8, f.size // 13), stroke_fill=(0, 0, 0))
    for mp in (ROOT / "maskot" / "logo.png", ROOT / "public" / "logo.png"):
        if mp.exists():
            try:
                s = int(w * (0.14 if h > w else 0.12)); lg = Image.open(mp).convert("RGBA").resize((s, s))
                img.paste(lg, (w - s - int(w * 0.03), int(h * 0.025)), lg)
            except Exception: pass
            break
    img.save(out, "JPEG", quality=92); return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="regen id tertentu saja (dipisah koma)")
    a = ap.parse_args()
    items = json.loads(CFG.read_text(encoding="utf-8"))
    if a.ids:
        want = set(x.strip() for x in a.ids.split(",") if x.strip())
        items = [it for it in items if it["id"] in want]
    elif a.test: items = items[:1]
    elif a.limit: items = items[:a.limit]
    for i, it in enumerate(items, 1):
        t0 = time.time()
        fmt = it.get("fmt", "16:9"); w, h, gw, gh = DIMS.get(fmt, DIMS["16:9"])
        out = OUTDIR / ((("TEST_" if a.test else "") + it["id"]) + ".jpg")
        try:
            overlay(gen_bg(it.get("query") or it["hook"], gw, gh, w, h), it["hook"], out, w, h)
            log(f"[{i}/{len(items)}] {it['id']} {fmt} ({int(time.time()-t0)}s) -> {out.name}")
        except Exception as e:
            log(f"[{i}/{len(items)}] {it['id']} GAGAL: {str(e)[:120]}")
    log("SELESAI gen.")

if __name__ == "__main__":
    main()
