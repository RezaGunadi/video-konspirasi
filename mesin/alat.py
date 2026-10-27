"""Alat bersama: lokasi folder, ffmpeg/ffprobe, unduhan, dan pembatalan."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

AKAR = Path(__file__).resolve().parent.parent
DATA = AKAR / "data"
PROYEK = DATA / "proyek"
CACHE = DATA / "cache"
OUTPUT = AKAR / "output"
INPUT = AKAR / "input"
MUSIK = AKAR / "musik"
PUBLIC = AKAR / "public"
for _d in (DATA, PROYEK, CACHE, OUTPUT, INPUT, MUSIK):
    _d.mkdir(parents=True, exist_ok=True)

WINDOWS = os.name == "nt"
# Laptop (Windows): alat & model di D:\tools. Mini PC (Linux): ~/tools. Bisa diganti lewat VIDEO_AI_TOOLS.
TOOLS = Path(os.environ.get("VIDEO_AI_TOOLS") or (r"D:\tools" if WINDOWS else Path.home() / "tools"))
HF_CACHE = Path(os.environ.get("HF_CACHE_DIR") or TOOLS / "hf-cache")  # model Whisper & kedalaman
FFMPEG_DIR = Path(os.environ.get("FFMPEG_DIR") or TOOLS / "ffmpeg" / "bin")
FFMPEG = str(FFMPEG_DIR / "ffmpeg.exe") if (FFMPEG_DIR / "ffmpeg.exe").exists() else "ffmpeg"
FFPROBE = str(FFMPEG_DIR / "ffprobe.exe") if (FFMPEG_DIR / "ffprobe.exe").exists() else "ffprobe"


def peramban():
    """Edge (Windows) atau Chromium/Chrome/Edge (Linux) untuk mode headless; "" kalau tidak ada."""
    if WINDOWS:
        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        return edge if os.path.exists(edge) else ""
    return next((p for p in map(shutil.which, ("microsoft-edge", "chromium", "chromium-browser", "google-chrome"))
                 if p), "")


# Font huruf tebal untuk teks di gambar (Pillow & ffmpeg drawtext). Linux: paket ttf-mscorefonts-installer atau
# salinan font di ~/.local/share/fonts; kalau tidak ada, DejaVu Sans Bold.
_FONT = {"impact": ("impact.ttf",), "arialbd": ("arialbd.ttf", "arial_bold.ttf"),
         "ariblk": ("ariblk.ttf", "arial_black.ttf")}
_FOLDER_FONT = [Path(r"C:\Windows\Fonts")] if WINDOWS else [
    Path.home() / ".local/share/fonts", Path.home() / ".fonts", Path("/usr/share/fonts/truetype/msttcorefonts"),
    Path("/usr/share/fonts")]


def font(nama):
    """Path file font (misalnya "impact") di OS ini."""
    dicari = {x.lower() for x in _FONT.get(nama, (f"{nama}.ttf",))}
    for folder in _FOLDER_FONT:
        if folder.is_dir():
            for f in folder.rglob("*.ttf"):
                if f.name.lower() in dicari:
                    return str(f)
    for f in (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),):
        if f.exists():
            return str(f)
    return str(_FOLDER_FONT[0] / next(iter(dicari)))


def font_ffmpeg(nama):
    """Path font untuk opsi fontfile ffmpeg (titik dua di "C:/" harus di-escape)."""
    return font(nama).replace("\\", "/").replace(":", "\\:")

UA = "VideoKonspirasiAI/1.0 (aplikasi desktop pribadi; python-requests)"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Dibatalkan(Exception):
    pass


class Batal:
    """Tanda batal per proyek; proses ffmpeg yang sedang jalan ikut dihentikan."""

    def __init__(self):
        self._ev = threading.Event()
        self._procs = set()
        self._lock = threading.Lock()

    def set(self):
        self._ev.set()
        with self._lock:
            for p in list(self._procs):
                try:
                    p.kill()
                except Exception:
                    pass

    def cek(self):
        if self._ev.is_set():
            raise Dibatalkan()

    @property
    def aktif(self):
        return self._ev.is_set()

    def daftar(self, p):
        with self._lock:
            self._procs.add(p)

    def lepas(self, p):
        with self._lock:
            self._procs.discard(p)


def jalankan(args, batal=None, timeout=1800, cwd=None):
    """Jalankan ffmpeg/ffprobe. Mengembalikan stdout; error membawa ekor stderr."""
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                         creationflags=NO_WINDOW)
    if batal:
        batal.daftar(p)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        raise RuntimeError(f"Waktu habis: {Path(args[0]).name}")
    finally:
        if batal:
            batal.lepas(p)
    if batal and batal.aktif:
        raise Dibatalkan()
    if p.returncode != 0:
        ekor = err.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise RuntimeError(f"{Path(args[0]).name} gagal: " + " | ".join(ekor))
    return out.decode("utf-8", "replace")


def ffmpeg(args, batal=None, timeout=1800, cwd=None):
    return jalankan([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], batal, timeout, cwd)


def probe(path_or_url, timeout=60):
    """Durasi, lebar, tinggi, dan ada-tidaknya video/audio."""
    out = jalankan([FFPROBE, "-v", "error", "-user_agent", UA, "-show_entries",
                    "format=duration:stream=codec_type,width,height,duration",
                    "-of", "json", str(path_or_url)], timeout=timeout)
    d = json.loads(out or "{}")
    info = {"durasi": 0.0, "lebar": 0, "tinggi": 0, "video": False, "audio": False}
    try:
        info["durasi"] = float(d.get("format", {}).get("duration") or 0)
    except ValueError:
        pass
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not info["video"]:
            info["video"] = True
            info["lebar"], info["tinggi"] = int(s.get("width") or 0), int(s.get("height") or 0)
            if not info["durasi"]:
                try:
                    info["durasi"] = float(s.get("duration") or 0)
                except ValueError:
                    pass
        elif s.get("codec_type") == "audio":
            info["audio"] = True
    return info


_sesi = requests.Session()
_sesi.headers["User-Agent"] = UA


# Jeda minimal antar-permintaan per situs. API Wikimedia (Wikipedia/Commons) membalas 429 kalau dibanjiri
# permintaan beruntun, termasuk dari pencarian paralel.
JEDA_SITUS = {"wikipedia.org": 0.5, "wikimedia.org": 0.5}
_jeda_lock = threading.Lock()
_terakhir = {}


def _tunggu_giliran(url):
    host = re.sub(r"^https?://([^/]+).*", r"\1", url)
    situs = next((s for s in JEDA_SITUS if host.endswith(s)), None)
    if not situs:
        return
    with _jeda_lock:
        tunggu = _terakhir.get(situs, 0) + JEDA_SITUS[situs] - time.time()
        if tunggu > 0:
            time.sleep(tunggu)
        _terakhir[situs] = time.time()


def http_get(url, ulang=4, **kw):
    kw.setdefault("timeout", 30)
    for coba in range(ulang):
        try:
            _tunggu_giliran(url)
            r = _sesi.get(url, **kw)
            if (r.status_code == 429 or r.status_code >= 500) and coba < ulang - 1:
                saran = r.headers.get("retry-after", "")
                time.sleep(min(20, int(saran)) if saran.isdigit() else 3 + coba * 4)
                continue
            return r
        except requests.RequestException:
            if coba == ulang - 1:
                raise
            time.sleep(2)
    return r


CURL = r"C:\Windows\System32\curl.exe" if WINDOWS else (shutil.which("curl") or "")


def _unduh_curl(url, sementara, batas_mb, batal, headers):
    """upload.wikimedia.org membalas 429 untuk klien HTTP Python (dibedakan dari sidik koneksinya, bukan
    User-Agent), sedangkan curl bawaan Windows dilayani normal. Jadi file Wikimedia diunduh lewat curl.exe."""
    args = [CURL, "-s", "-L", "-f", "--retry", "3", "--retry-delay", "5", "--max-time", "300",
            "--max-filesize", str(batas_mb * 1024 * 1024), "-A", UA, "-o", str(sementara)]
    rentang = (headers or {}).get("Range", "")
    if rentang.startswith("bytes="):
        args += ["-r", rentang[6:]]
    _tunggu_giliran(url)
    try:
        jalankan(args + [url], batal, timeout=330)
    except RuntimeError:
        return False
    return sementara.exists() and sementara.stat().st_size > 0


def unduh(url, tujuan, batas_mb=150, batal=None, headers=None):
    """Unduh ke file (atomic). Mengembalikan path, atau None jika terlalu besar/gagal."""
    tujuan = Path(tujuan)
    if tujuan.exists() and tujuan.stat().st_size > 0:
        return tujuan
    sementara = tujuan.with_suffix(tujuan.suffix + ".part")
    if re.match(r"^https://(upload|thumb)\.wikimedia\.org/", url) and os.path.exists(CURL):
        if _unduh_curl(url, sementara, batas_mb, batal, headers):
            os.replace(sementara, tujuan)
            return tujuan
        sementara.unlink(missing_ok=True)
        return None
    try:
        for coba in range(3):
            _tunggu_giliran(url)
            r = _sesi.get(url, stream=True, timeout=60, headers=headers or {})
            if r.status_code != 429 and r.status_code < 500:
                break
            saran = r.headers.get("retry-after", "")
            r.close()
            if coba < 2:  # server sibuk/membatasi: tunggu sebentar lalu coba lagi
                time.sleep(min(15, int(saran)) if saran.isdigit() else 3 + coba * 4)
        with r:
            if r.status_code not in (200, 206):
                return None
            ukuran = int(r.headers.get("content-length") or 0)
            if ukuran and ukuran > batas_mb * 1024 * 1024:
                return None
            total = 0
            with open(sementara, "wb") as f:
                for blok in r.iter_content(1 << 16):
                    if batal:
                        batal.cek()
                    f.write(blok)
                    total += len(blok)
                    if total > batas_mb * 1024 * 1024:
                        raise ValueError("terlalu besar")
        os.replace(sementara, tujuan)
        return tujuan
    except Dibatalkan:
        sementara.unlink(missing_ok=True)
        raise
    except Exception:
        sementara.unlink(missing_ok=True)
        return None


def hash_pendek(teks):
    return hashlib.sha1(teks.encode("utf-8")).hexdigest()[:12]


def slug(teks, maks=60):
    s = re.sub(r"[^0-9a-zA-Z]+", "-", teks.lower()).strip("-")
    return (s[:maks].rstrip("-") or "video")


def baca_json(path, bawaan=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return bawaan


def tulis_json(path, data):
    """Tulis atomik. Nama file sementara unik per thread (log() dipanggil dari thread pencarian paralel), dan
    os.replace dicoba ulang: di Windows antivirus/indexer sesaat mengunci file baru (WinError 32) — dulu itu
    menggagalkan proses footage yang sudah berjalan 38 menit."""
    path = Path(path)
    sementara = path.with_name(f"{path.stem}.{os.getpid()}-{threading.get_ident()}.tmp")
    with open(sementara, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for coba in range(20):
        try:
            os.replace(sementara, path)
            return
        except PermissionError:
            if coba == 19:
                sementara.unlink(missing_ok=True)
                raise
            time.sleep(0.05 + coba * 0.05)
