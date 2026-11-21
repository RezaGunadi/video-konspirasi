# -*- coding: utf-8 -*-
"""Re-thumbnail video yang SUDAH diupload (frame sumber banyak kehapus).
Background: Wikimedia Commons (gratis, no-key) sesuai 'query'; fallback gradien + emoji kalau tak ada.
Overlay: teks hook bold (Impact kuning + outline) + maskot. Set ke video via API.

Config: rahasia/sains_thumbs.json = [{id, hook, query, emoji}].
  python yt_thumb.py --test [N]             # generate N entri pertama ke rahasia/thumb2 (TANPA set) buat dilihat
  python yt_thumb.py --token yt_token.json  # generate + set semua
"""
import sys, json, io, time, argparse, urllib.parse, urllib.request, hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent
RAHASIA = ROOT / "rahasia"
CFG = RAHASIA / "sains_thumbs.json"
OUTDIR = RAHASIA / "thumb2"; OUTDIR.mkdir(parents=True, exist_ok=True)
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
W, H = 1280, 720
UA = {"User-Agent": "KepoThumb/1.0 (educational thumbnails; contact via youtube)"}
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def log(t): print(t, flush=True)

def _font(path_opts, size):
    for p in path_opts:
        if Path(p).exists():
            try: return ImageFont.truetype(p, size)
            except Exception: pass
    return ImageFont.load_default()
def impact(size): return _font([r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf"], size)
def emoji_font(size):
    try: return ImageFont.truetype(r"C:\Windows\Fonts\seguiemj.ttf", size)
    except Exception: return None

def _get(url, timeout=40):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def wiki_bg(query):
    """Cari foto landscape di Wikimedia Commons. Return Image 1280x720 cover-crop, atau None."""
    api = "https://commons.wikimedia.org/w/api.php"
    try:
        q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": f"{query} filetype:bitmap",
                                    "srnamespace": "6", "srlimit": "12", "format": "json"})
        titles = [r["title"] for r in json.loads(_get(f"{api}?{q}", 30))["query"]["search"]]
    except Exception as e:
        log(f"   wiki search gagal: {str(e)[:50]}"); return None
    for title in titles:
        try:
            q2 = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo",
                                         "iiprop": "url|size|mime", "iiurlwidth": "1600", "format": "json"})
            page = next(iter(json.loads(_get(f"{api}?{q2}", 30))["query"]["pages"].values()))
            ii = page["imageinfo"][0]
            if "svg" in ii.get("mime", "") or "pdf" in ii.get("mime", ""): continue
            tw, th = ii.get("thumbwidth", 0), ii.get("thumbheight", 0)
            if not tw or not th or tw / th < 1.15: continue           # mau landscape
            img = Image.open(io.BytesIO(_get(ii.get("thumburl") or ii["url"], 60))).convert("RGB")
            s = max(W / img.width, H / img.height)
            img = img.resize((int(img.width * s), int(img.height * s)))
            x, y = (img.width - W) // 2, (img.height - H) // 2
            return img.crop((x, y, x + W, y + H))
        except Exception:
            continue
    return None

def grad_bg(seed, emoji):
    """Gradien diagonal (warna unik per-topik dari seed) + emoji besar sebagai fokus (kiri-atas, lepas dari maskot)."""
    import colorsys
    h1 = (int(hashlib.md5(seed.encode()).hexdigest(), 16) % 360) / 360.0
    def rgb(hh, s, v): return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hh, s, v))
    c_top, c_bot = rgb(h1, 0.62, 0.46), rgb((h1 + 0.07) % 1, 0.72, 0.09)
    base = Image.new("RGB", (W, H), c_bot); top = Image.new("RGB", (W, H), c_top)
    mask = Image.new("L", (W, H)); md = ImageDraw.Draw(mask)
    for yy in range(H): md.line([(0, yy), (W, yy)], fill=int(255 * (1 - yy / H)))   # atas lebih terang
    img = Image.composite(top, base, mask)
    ef = emoji_font(300)
    if ef and emoji:
        try:
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(lay).text((95, 55), emoji, font=ef, embedded_color=True)   # kiri-atas, besar
            lay.putalpha(lay.getchannel("A").point(lambda a: int(a * 0.9)))
            img = Image.alpha_composite(img.convert("RGBA"), lay).convert("RGB")
        except Exception: pass
    return img

def _wrap_fit(draw, text, maxw, maxh, start=168):
    size = start
    while size > 52:
        f = impact(size)
        words = text.upper().split(); lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if draw.textlength(t, font=f) <= maxw: cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        lh = int(size * 1.03)
        if len(lines) <= 3 and lh * len(lines) <= maxh and all(draw.textlength(l, font=f) <= maxw for l in lines):
            return f, lines, lh
        size -= 6
    return impact(52), [text.upper()], 56

def buat(query, hook, emoji, out):
    img = grad_bg(query or hook, emoji)      # gradien+emoji (reliable; Pollinations paywalled, Wikimedia tak reliable)
    # gradien gelap bawah biar teks pop
    grad = Image.new("L", (1, H), 0)
    for yy in range(H):
        grad.putpixel((0, yy), int(238 * max(0, (yy - H * 0.40) / (H * 0.60)) ** 1.25))
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, grad.resize((W, H)))
    d = ImageDraw.Draw(img)
    f, lines, lh = _wrap_fit(d, hook, W - 110, H * 0.46)
    y0 = H - lh * len(lines) - 42
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f); x = (W - tw) // 2
        d.text((x, y0 + i * lh), ln, font=f, fill=(255, 232, 0), stroke_width=max(8, f.size // 13), stroke_fill=(0, 0, 0))
    for mp in (ROOT / "maskot" / "logo.png", ROOT / "public" / "logo.png"):
        if mp.exists():
            try:
                s = int(W * 0.12); lg = Image.open(mp).convert("RGBA").resize((s, s))
                img.paste(lg, (W - s - int(W * 0.02), int(H * 0.035)), lg)
            except Exception: pass
            break
    img.save(out, "JPEG", quality=92)
    return out

def build_service(token_path):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request()); token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="yt_token.json")
    ap.add_argument("--test", nargs="?", const=1, type=int, help="generate N pertama ke thumb2, TANPA set")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    items = json.loads(CFG.read_text(encoding="utf-8"))
    if a.test:
        for it in items[:a.test]:
            out = OUTDIR / f"TEST_{it['id']}.jpg"
            log(f"[{it['id']}] query='{it.get('query')}'")
            buat(it.get("query", ""), it["hook"], it.get("emoji", ""), out)
            log(f"  -> {out}")
            time.sleep(1)
        return
    if a.limit: items = items[:a.limit]
    svc = build_service(RAHASIA / a.token)
    from googleapiclient.http import MediaFileUpload
    ok = 0
    for it in items:
        try:
            out = OUTDIR / f"{it['id']}.jpg"
            buat(it.get("query", ""), it["hook"], it.get("emoji", ""), out)
            svc.thumbnails().set(videoId=it["id"], media_body=MediaFileUpload(str(out))).execute()
            ok += 1; log(f"  OK {it['id']} | {it['hook'][:38]}")
        except Exception as e:
            log(f"  GAGAL {it['id']}: {str(e)[:120]}")
        time.sleep(1)
    log(f"Selesai: {ok}/{len(items)} thumbnail di-set.")

if __name__ == "__main__":
    main()
