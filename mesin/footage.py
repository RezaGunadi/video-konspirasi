"""Mencari footage legal & gratis per adegan, memilih yang paling pas, lalu mengunduhnya.

Sumber tanpa login/API key:
- Wikimedia Commons (foto & video), NASA Image Library (foto & video luar angkasa)
- Internet Archive (film arsip public domain: Prelinger + item bertanda Public Domain)
- Openverse (gabungan foto berlisensi bebas dari Flickr, museum, dll.; dibatasi ±200 pencarian/hari per IP)
- The Met & Cleveland Museum of Art (lukisan, ukiran, peta lama — public domain/CC0)
Opsional dengan API key gratis: Pexels dan Pixabay (stock video HD).
"""
import base64
import html
import json
import math
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlencode

import requests

from . import ollama, potong
from .alat import (CACHE, FFMPEG, NO_WINDOW, Dibatalkan, baca_json, ffmpeg, font_ffmpeg, hash_pendek, http_get,
                   peramban, probe, tulis_json, unduh)

F_CARI = CACHE / "cari"
F_ASET = CACHE / "aset"
F_THUMB = CACHE / "thumb"
for _d in (F_CARI, F_ASET, F_THUMB):
    _d.mkdir(parents=True, exist_ok=True)

KATA_UMUM = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "with", "to", "for", "from", "by", "is", "old",
             "view", "close", "up"}
PRIOR = {"Pexels": 0.5, "Pixabay": 0.4, "Mixkit": 0.45, "Wikimedia": 0.25, "NASA": 0.25, "Openverse": 0.3,
         "The Met": 0.2, "Cleveland Museum": 0.2, "Archive.org": 0.0}
# Judul item Archive.org yang biasanya rekaman orang bicara (bukan footage) atau unggahan ulang.
ARSIP_BUANG = re.compile(r"podcast|interview|conversation|episode|\blive\b|stream|radio|talk show|webinar|"
                         r"audiobook|lecture|vlog", re.I)
# Video berita/politik: AI kadang salah membaca thumbnail-nya (berita perang dianggap "berita Nessie").
BERITA = re.compile(r"\bVOA\b|\bnews\b|outrag|\bclaims?\b|\bsays\b|speech|press conference|interview|president|"
                    r"election|trump|biden|putin|zelensky|parliament|minister|\bwar\b|killing|protest", re.I)
# Benda yang hanya MEMAKAI nama subjek (wahana "Loch Ness Monster" di Busch Gardens, hotel, toko, suvenir...).
# AI vision bisa tertipu (roller coaster di atas air dibaca "Pemandangan Danau Loch Ness"), jadi disaring
# dari judul/deskripsinya.
BUKAN_SUBJEK = re.compile(
    r"roller ?coaster|\bcoaster|amusement|theme park|busch gardens|six flags|disney|"
    r"universal studios|water ?park|wahana|taman hiburan|souvenir|suvenir|"
    r"merchandise|t-shirt|keychain|plush|\blego\b|\btoys?\b|mainan|costume|cosplay|"
    r"mascot|maskot|restaurant|restoran|\bcafe\b|\bhotel\b|\bmotel\b|\bshop\b|"
    r"\bstore\b|\btoko\b|billboard|\bbus\b|\btram\b|parade|mural|graffiti|grafiti|poster|\bfilm\b|"
    r"\bmovie\b|trailer|swimming|\bpool\b|kolam renang|fishing tackle|tackle shop|\bbrand\b|\blogo\b|"
    # foto pribadi/keluarga (Openverse/Flickr: "Landon With Giant Painted Pig" lolos sebagai "bukti raksasa")
    r"\bbaby\b|\bbabies\b|toddler|newborn|\bkids?\b|\bchild(ren)?\b|selfie|birthday|wedding|\bfamily\b|vacation|"
    r"my (son|daughter|wife|husband|dog|cat)|grandson|granddaughter|\bbayi\b|ulang tahun|"
    # kartun, game, fan-art (fan-art Pokémon "based on Maushop" pernah jadi panel perbandingan)
    r"pok[eé]mon|\banime\b|\bmanga\b|cartoon|kartun|chibi|fan ?art|fanart|minecraft|roblox|fortnite|"
    r"\bvideo ?game\b|\bgameplay\b|\bfunko\b|action figure|figurine|"
    # daging/bangkai/sabung: "Chickens in market" (ayam potong tergantung) pernah jadi shot penutup video dinosaurus
    r"carcass|slaughter|butcher|plucked|\bmeat\b|poultry market|chickens? in (a )?market|daging|cock ?fight|"
    r"chicken fight|sabung", re.I)
_openverse_habis = 0.0  # waktu sampai Openverse boleh dipakai lagi setelah kena batas harian
# Film arsip, siaran, dan ceramah: kartu judul, angka hitung mundur "31", kredit "Produced in Technicolor", wajah
# narasumber. Di video sains muncul karena namanya kebetulan sama ("Mariana Trench" → film Perang Dunia II di
# Kepulauan Mariana, "Chabar Dai Toa"). Hanya dipakai kalau narasi adegannya memang membahas masa lalu (ada tahunnya).
ARSIP = re.compile(r"\b(1[89]\d\d|19[0-7]\d)\b|newsreel|propaganda|technicolor|\breels?\b|leathernecks?|"
                   r"marine corps|\bnavy\b|\barmy\b|nippon|eiga|film corporation|universal news|pathe|"
                   r"lecture|webinar|seminar|keynote|symposium|panel discussion|town hall|podcast|"
                   r"\btalks?\b|beyond the data|culture of|safety training|training film|educational film|"
                   # film koleksi arsip nasional AS ("Deep Sea Fishing in Florida (31-MP-611)", film rumahan Hoover)
                   r"\b\d{2,3}-[a-z]{1,4}-\d+\b|home movie|kodacolor|kodachrome|national archives|"
                   r"presidential library", re.I)
# Kata umum di kueri latar yang tidak menentukan tempat ("deep sea underwater" → "deep sea", "underwater"). Termasuk
# kata bentuk visual: "earth globe animation" pernah mendapat "Digital animation of screens" (layar TV statis).
_UMUM_LATAR = {"aerial", "view", "views", "drone", "close", "closeup", "up", "timelapse", "time", "lapse", "footage",
               "video", "shot", "slow", "motion", "background", "scene", "landscape", "beautiful", "over", "into",
               "animation", "animated", "digital", "abstract", "simulation", "render", "cgi", "graphic", "graphics",
               "3d", "4k", "hd", "loop", "cinematic", "clip", "stock", "moving", "flying", "camera"}
# Klip cuaca/bencana (citra satelit badai, banjir, kebakaran) hanya jadi latar kalau kuerinya memang meminta itu:
# "tropical island coast" pernah mendapat "Ernesto Brings Dangerous Seas to North America's Atlantic Coast" (Hurricane
# Ernesto) untuk narasi evolusi komodo.
# Tanpa \b di depan: kata gabungan ("Bushfires and Grassfires dot the Australian Outback", "thunderstorm") ikut.
PERISTIWA = re.compile(r"hurricanes?|cyclones?|typhoons?|storms?\b|tornado(es)?|floods?\b|flooding|tsunami|"
                       r"earthquakes?|fires?\b|disasters?|drought|landslides?|avalanches?|blizzard|"
                       r"\bwar\b|explosion|crash", re.I)
# Kata sifat di kueri latar: ikut menjelaskan tempatnya, tapi judul klip yang hanya cocok di kata sifat ("Tropical
# Cyclone", "Deep Purple") belum tentu tempat itu.
_SIFAT_LATAR = {"tropical", "ancient", "deep", "deepest", "dark", "green", "snowy", "rocky", "frozen", "arid", "hot",
                "cold", "icy", "sandy", "foggy", "misty", "volcanic", "rainy", "dry", "wet", "wild", "giant", "huge",
                "vast", "massive", "remote", "small", "large", "big", "old", "dense", "barren", "lush", "blue", "red",
                "white", "black", "golden", "tall", "high", "low", "wide", "beautiful", "stormy", "calm"}


def _kata(teks):
    return [k for k in re.findall(r"[a-z0-9]+", (teks or "").lower()) if k not in KATA_UMUM]


# Klip yang subjeknya ORANG (judul atau isi menurut juri AI). Untuk narasi tentang hewan/alam, juri AI pernah memberi
# 8/8 ke "Boxers hitting in a fight" untuk komodo yang bertarung; begitu juga wanita melambai di dermaga, pria
# salto di pantai, dan pemain ski sebagai latar.
_ORANG_JUDUL = re.compile(r"\b(man|men|woman|women|people|person|boy|girl|kids?|child|children|couple|tourists?|"
                          r"boxers?|boxing|athletes?|players?|crowd|dancers?|dancing|skiers?|surfers?|soldiers?|"
                          r"police|reporter|presenter|businessman|family|friends|lady|guy|selfie)\b", re.I)
_ORANG_ISI = re.compile(r"\b(pria|wanita|orang|perempuan|laki-laki|anak-anak|petinju|penari|turis|wisatawan|tentara|"
                        r"polisi|pemain|atlet|kerumunan|pasangan|reporter|pembawa acara)\b", re.I)
_NARASI_ORANG = re.compile(r"\b(manusia|orang|ilmuwan|peneliti|penduduk|warga|pendaki|penyelam|nelayan|pemburu|"
                           r"turis|wisatawan|penjelajah|tentara|petani|suku|masyarakat|pria|wanita|tokoh|raja|ratu|"
                           r"presiden|astronot|arkeolog|pelaut|penambang|pekerja)\w*", re.I)


def orang_tak_relevan(k, narasi):
    """Klip video yang subjeknya orang, padahal narasinya tidak membahas manusia. Isi dari juri AI hanya dilihat kata
    pertamanya (subjeknya): "Komodo berjalan di dekat orang" tetap klip komodo."""
    if k.get("jenis") != "video":
        return False
    orang = _ORANG_JUDUL.search(k.get("judul") or k.get("teks") or "") or \
        _ORANG_ISI.match((k.get("isi_ai") or "").strip())
    return bool(orang) and not _NARASI_ORANG.search(narasi or "")


def arsip_tak_relevan(k, narasi):
    """Film arsip/siaran/ceramah yang tidak dibutuhkan narasi (narasinya tidak menyebut tahun lampau)."""
    if k.get("jenis") != "video" or not ARSIP.search(f"{k.get('judul') or ''} {k.get('teks') or ''}"):
        return False
    return not re.search(r"\b(1[0-9]\d\d|19[0-8]\d)\b", narasi or "")


def _akar(w):
    """Bentuk tunggal sederhana kata Inggris: galaxies → galaxy, volcanoes → volcano, dunes → dune."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("oes", "xes", "ches", "shes", "sses")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


_AKHIRAN = ("s", "es", "n", "an", "ern", "ic", "al", "er", "est", "y", "ing", "ed")


def _kata_sama(a, b):
    """Kata yang sama atau turunannya (sahara/saharan, deep/deepest, ocean/oceanic) — bukan sekadar awalan
    ("sand" ≠ "sandbar")."""
    pendek, panjang = sorted((_akar(a), _akar(b)), key=len)
    return pendek == panjang or (len(pendek) >= 3 and panjang.startswith(pendek)
                                 and panjang[len(pendek):] in _AKHIRAN)


def cocok_judul(k, kueri):
    """Judul klip menyebut tempat yang dicari ("Underwater view of a coral reef" untuk "deep sea underwater"). Klip
    latar yang TIDAK dinilai AI hanya dipakai kalau cocok begini. Hanya judulnya, kata utuh: dulu keterangan panjang
    ikut dicocokkan per potongan kata, jadi "desert sand dunes" mendapat akrobat di pantai ("…on the sand near the
    seashore"), pulau pasir ("Sandbar island"), dan festival "Halloween Weekend 2016". Kata sifat saja tidak cukup:
    "tropical island beach" pernah mendapat "Tropical Cyclone Freddy" (citra satelit badai)."""
    kata = [w for w in _kata(kueri) if w not in _UMUM_LATAR and len(w) >= 3]
    kata = [w for w in kata if w not in _SIFAT_LATAR] or kata
    judul = _kata(k.get("judul") or k.get("teks") or "")
    if PERISTIWA.search(f"{k.get('judul') or ''} {k.get('teks') or ''}") and not PERISTIWA.search(kueri):
        return False
    return any(_kata_sama(w, x) for w in kata for x in judul)


def klip_latar(cfg, kueri, format_video, kecuali=(), narasi="", log=print, maks=4):
    """Klip suasana untuk adegan yang tidak punya klip yang pas: dicari dengan kueri latar dari AI (tempat di dunia
    topik video: "deep sea underwater"), adegan ini dulu lalu adegan-adegan terdekat. Dulu daftar cadangan tetap
    ("desert dunes aerial", "mountains aerial") — narasi lempeng di dasar Samudra Pasifik tampil dengan unta di gurun.
    Mengembalikan (kueri_terpakai, [kandidat ditandai cadangan])."""
    for q in [x for x in dict.fromkeys(kueri) if x][:3]:
        try:
            ks = cari_kandidat(cfg, "", q, format_video, log, video=True)
        except Exception as e:
            log(f"  Klip latar “{q}” gagal dicari: {e}")
            continue
        cocok = [k for k in ks if k["jenis"] == "video" and k["id"] not in kecuali and cocok_judul(k, q)
                 and not arsip_tak_relevan(k, narasi) and not BUKAN_SUBJEK.search(k.get("judul") or "")]
        if cocok:
            return q, [{**k, "cadangan": True, "kueri": q} for k in cocok[:maks]]
    return "", []


def _bersih_html(t):
    teks = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    teks = re.sub(r"^\s*Related names:\s*", "", teks, flags=re.I)
    return " ".join(teks.split())


def _cache(nama, fungsi, umur_hari=7):
    path = F_CARI / f"{hash_pendek(nama)}.json"
    d = baca_json(path)
    if d and time.time() - d.get("waktu", 0) < umur_hari * 86400:
        return d["hasil"]
    hasil = fungsi()
    tulis_json(path, {"waktu": time.time(), "nama": nama, "hasil": hasil})
    return hasil


# ---------------------------------------------------------------- sumber

def pexels_video(q, orient, key):
    def f():
        r = http_get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                     params={"query": q, "per_page": 12, "orientation": orient, "size": "medium"})
        if not r.ok:
            return []
        hasil = []
        for v in r.json().get("videos", []):
            files = [x for x in v.get("video_files", []) if x.get("file_type") == "video/mp4" and x.get("width")]
            if not files:
                continue
            cukup = [x for x in files if min(x["width"], x["height"]) >= 1080]
            pilih = min(cukup, key=lambda x: x["width"] * x["height"]) if cukup else max(files, key=lambda x: x["width"])
            slug_url = v.get("url", "").rstrip("/").split("/")[-1]
            hasil.append({"id": f"pexels-v-{v['id']}", "sumber": "Pexels", "jenis": "video", "url": pilih["link"],
                          "thumb": v.get("image"), "teks": slug_url.replace("-", " "),
                          "lebar": pilih["width"], "tinggi": pilih["height"], "durasi": v.get("duration") or 0,
                          "lisensi": "Pexels License", "pembuat": (v.get("user") or {}).get("name", ""),
                          "halaman": v.get("url")})
        return hasil
    return _cache(f"pexels-v|{q}|{orient}", f)


def pexels_foto(q, orient, key):
    def f():
        r = http_get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                     params={"query": q, "per_page": 12, "orientation": orient})
        if not r.ok:
            return []
        return [{"id": f"pexels-f-{p['id']}", "sumber": "Pexels", "jenis": "gambar",
                 "url": p["src"]["original"] + "?auto=compress&cs=tinysrgb&w=2400", "thumb": p["src"].get("medium"),
                 "teks": (p.get("alt") or "") + " " + p.get("url", "").rstrip("/").split("/")[-1].replace("-", " "),
                 "lebar": p["width"], "tinggi": p["height"], "lisensi": "Pexels License",
                 "pembuat": p.get("photographer", ""), "halaman": p.get("url")}
                for p in r.json().get("photos", [])]
    return _cache(f"pexels-f|{q}|{orient}", f)


def pixabay_video(q, key):
    def f():
        r = http_get("https://pixabay.com/api/videos/", params={"key": key, "q": q[:100], "per_page": 12,
                                                               "safesearch": "true"})
        if not r.ok:
            return []
        hasil = []
        for h in r.json().get("hits", []):
            vs = h.get("videos", {})
            pilih = next((vs[k] for k in ("large", "medium", "small") if vs.get(k, {}).get("url")), None)
            if not pilih:
                continue
            hasil.append({"id": f"pixabay-v-{h['id']}", "sumber": "Pixabay", "jenis": "video", "url": pilih["url"],
                          "thumb": pilih.get("thumbnail") or vs.get("medium", {}).get("thumbnail"),
                          "teks": h.get("tags", ""), "lebar": pilih.get("width", 0), "tinggi": pilih.get("height", 0),
                          "durasi": h.get("duration") or 0, "lisensi": "Pixabay Content License",
                          "pembuat": h.get("user", ""), "halaman": h.get("pageURL")})
        return hasil
    return _cache(f"pixabay-v|{q}", f)


def pixabay_foto(q, orient, key):
    def f():
        r = http_get("https://pixabay.com/api/", params={
            "key": key, "q": q[:100], "per_page": 12, "image_type": "photo", "safesearch": "true",
            "orientation": "vertical" if orient == "portrait" else "horizontal"})
        if not r.ok:
            return []
        return [{"id": f"pixabay-f-{h['id']}", "sumber": "Pixabay", "jenis": "gambar", "url": h["largeImageURL"],
                 "thumb": h.get("webformatURL"), "teks": h.get("tags", ""), "lebar": h.get("imageWidth", 0),
                 "tinggi": h.get("imageHeight", 0), "lisensi": "Pixabay Content License",
                 "pembuat": h.get("user", ""), "halaman": h.get("pageURL")} for h in r.json().get("hits", [])]
    return _cache(f"pixabay-f|{q}|{orient}", f)


_MIXKIT_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/130 Safari/537.36"}
_mixkit_habis = 0.0  # Mixkit (Cloudflare) memblokir ±30 menit setelah ±100 permintaan beruntun
# Kata sifat suasana dari kata kunci "b" yang tidak punya halaman tag sendiri di Mixkit ("foggy lake night" → "lake").
_MIXKIT_SIFAT = {"dark", "foggy", "misty", "old", "ancient", "abandoned", "mysterious", "stormy", "eerie", "creepy",
                 "night", "aerial", "view", "close", "slow", "motion", "timelapse", "silhouette", "empty", "deep",
                 "black", "white", "cinematic", "gloomy", "vintage"}


def _mixkit_get(url):
    """GET ke mixkit.co tanpa ulang-coba panjang; kena blokir → Mixkit dilewati 30 menit (sumber lain jalan terus)."""
    global _mixkit_habis
    if time.time() < _mixkit_habis:
        return None
    r = requests.get(url, headers=_MIXKIT_UA, timeout=20)  # bukan http_get: ulang-coba saat 429 hanya membuang waktu
    if r.status_code == 429 or "<title>Just a moment" in r.text[:3000]:
        _mixkit_habis = time.time() + 1800
        raise RuntimeError("Mixkit sedang membatasi akses, dilewati 30 menit")
    return r if r.ok else None


def _mixkit_item(halaman):
    """Lisensi + file video satu item Mixkit (dari JSON-LD halaman itemnya). Hanya "Free" (Stock Video Free License)
    yang boleh untuk YouTube/monetisasi; item "Mixkit Restricted License" hanya untuk proyek pribadi non-komersial.
    Gagal = exception (tidak di-cache, supaya item yang kena blokir tidak dianggap bukan-Free selama 30 hari)."""
    def f():
        r = _mixkit_get(halaman)
        if r is None:
            raise RuntimeError("halaman item Mixkit tidak terbuka")
        lisensi = re.search(r'"copyrightNotice":"([^"]+)"', r.text)
        url = re.search(r'"contentUrl":"(https://assets\.mixkit\.co/[^"]+\.mp4)"', r.text)
        return {"lisensi": lisensi.group(1) if lisensi else "", "url": url.group(1) if url else ""}
    return _cache(f"mixkit-item|{halaman}", f, umur_hari=30)


def _mixkit_ld(teks):
    """Klip di JSON-LD halaman tag Mixkit (/free-stock-video/fog/): lisensinya langsung tertulis."""
    hasil = []
    for m in re.finditer(r'<script[^>]*ld\+json[^>]*>(.*?)</script>', teks, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for g in (d.get("@graph") or [d]) if isinstance(d, dict) else []:
            if g.get("@type") == "VideoObject" and g.get("contentUrl"):
                hasil.append({"halaman": str(g.get("@id", "")).split("#")[0], "judul": g.get("name", ""),
                              "teks": g.get("description", ""), "url": g["contentUrl"],
                              "thumb": g.get("thumbnailUrl"), "lisensi": g.get("copyrightNotice", "")})
    return hasil


def _mixkit_kartu(teks):
    """Kartu hasil di halaman discover Mixkit (lisensi belum diketahui, dicek per item)."""
    kartu = []
    for k in teks.split('class="item-grid__item"')[1:]:
        judul = re.search(r'item-grid-card__title[^>]*>\s*<a href="(/free-stock-video/[^"]+)">([^<]+)</a>', k)
        pratinjau = re.search(r'https://assets\.mixkit\.co/[^"\s]+?-360\.mp4', k)
        if not judul or not pratinjau:
            continue
        desk = re.search(r'item-grid-card__description[^>]*>([^<]+)<', k)
        poster = re.search(r'https://assets\.mixkit\.co/[^"\s]+?-thumb-360-0\.jpg', k)
        kartu.append({"halaman": "https://mixkit.co" + judul.group(1), "judul": html.unescape(judul.group(2)).strip(),
                      "teks": html.unescape(desk.group(1)).strip() if desk else "",
                      "url": pratinjau.group(0).replace("-360.mp4", "-720.mp4"),
                      "thumb": poster.group(0) if poster else None})
    return kartu


def mixkit(q):
    """Stock video HD gratis dari Mixkit tanpa login/API key. Frasa dicari di halaman discover (lisensi dicek per
    item, maksimal 6), lalu kalau kurang, kata bendanya di halaman tag (lisensi sudah tertulis). Hanya item
    berlisensi Free yang dipakai."""
    if time.time() < _mixkit_habis:
        return []

    def f():
        kata = re.findall(r"[a-z0-9]+", q.lower())
        benda = [k for k in kata if k not in _MIXKIT_SIFAT and len(k) > 2]
        dapat, lihat = [], set()
        langkah = ([("discover", "-".join(kata))] if len(kata) > 1 else []) + \
            [("tag", k) for k in reversed(benda or kata)][:2]
        for jenis, kunci in langkah:
            if len(dapat) >= 4:
                break
            r = _mixkit_get(f"https://mixkit.co/free-stock-video/{'discover/' if jenis == 'discover' else ''}{kunci}/")
            if r is None:
                continue
            if jenis == "tag":
                calon = _mixkit_ld(r.text)
            else:
                calon = _mixkit_kartu(r.text)[:6]
                with ThreadPoolExecutor(max_workers=3) as kolam:
                    def cek(x):
                        try:
                            return _mixkit_item(x["halaman"])
                        except Exception:
                            return {}
                    for x, d in zip(calon, kolam.map(cek, calon)):
                        x["lisensi"], x["url"] = d.get("lisensi", ""), d.get("url") or x["url"]
            for x in calon:
                if (x.get("lisensi") or "").strip().lower() == "free" and x["halaman"] not in lihat:
                    lihat.add(x["halaman"])
                    dapat.append(x)
        hasil = []
        for x in dapat:
            nomor = x["halaman"].rstrip("/").rsplit("-", 1)[-1]
            hasil.append({"id": f"mixkit-{nomor}", "sumber": "Mixkit", "jenis": "video", "url": x["url"],
                          "thumb": x.get("thumb"), "teks": f"{x['judul']} {x['teks']}"[:300], "judul": x["judul"],
                          "lebar": 1920, "tinggi": 1080, "durasi": 0, "lisensi": "Mixkit Stock Video Free License",
                          "pembuat": "Mixkit", "halaman": x["halaman"]})
        return hasil
    return _cache(f"mixkit2|{q}", f)


def _transcode_terbaik(ii):
    """Video Wikimedia: pakai transcode ≤1080p. File asli (bisa 4K, ratusan MB) ditolak server dengan 429."""
    pilihan = [d for d in ii.get("derivatives") or []
               if d.get("transcodekey") and (d.get("height") or 0) <= 1080 and "webm" in d.get("transcodekey", "")]
    if pilihan:
        return max(pilihan, key=lambda d: d.get("height") or 0)
    if (ii.get("size") or 0) < 150 * 1024 * 1024:
        return {"src": ii.get("url"), "width": ii.get("width"), "height": ii.get("height")}
    return None


def wikimedia(q, jenis="gambar"):
    def f():
        v = jenis == "video"
        pre = "vi" if v else "ii"
        r = http_get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 12,
            "gsrsearch": f"{q} filetype:{'video' if v else 'bitmap'}",
            "prop": "videoinfo" if v else "imageinfo",
            f"{pre}prop": "url|size|mime|extmetadata" + ("|derivatives" if v else ""), f"{pre}urlwidth": 1920,
            f"{pre}extmetadatafilter": "LicenseShortName|Artist|ImageDescription"})
        if not r.ok:
            return []
        hasil = []
        for p in (r.json().get("query", {}).get("pages") or {}).values():
            ii = (p.get("videoinfo" if v else "imageinfo") or [{}])[0]
            mime = ii.get("mime", "")
            if not v and (mime == "image/gif" or (ii.get("width") or 0) < 700):
                continue
            em = ii.get("extmetadata", {})
            judul = p.get("title", "").replace("File:", "")
            judul_bersih = re.sub(r"\.\w+$", "", judul).replace("_", " ")
            if v and BERITA.search(judul_bersih):
                continue
            url, lebar, tinggi = ii.get("thumburl"), ii.get("width", 0), ii.get("height", 0)
            if v:
                t = _transcode_terbaik(ii)
                if not t:
                    continue
                url, lebar, tinggi = t["src"], t.get("width") or lebar, t.get("height") or tinggi
            hasil.append({"id": f"wiki-{p.get('pageid')}", "sumber": "Wikimedia", "jenis": jenis,
                          "url": url, "thumb": ii.get("thumburl"), "segmen": v,
                          "durasi": ii.get("duration") or 0,
                          "teks": judul_bersih + " " + _bersih_html(em.get("ImageDescription", {}).get("value"))[:200],
                          "lebar": lebar, "tinggi": tinggi,
                          "lisensi": _bersih_html(em.get("LicenseShortName", {}).get("value")) or "lihat halaman",
                          "pembuat": _bersih_html(em.get("Artist", {}).get("value"))[:80],
                          "halaman": ii.get("descriptionurl"), "judul": judul_bersih})
        return [h for h in hasil if h["url"]]
    return _cache(f"wiki2|{jenis}|{q}", f)


def nasa(q):
    def f():
        r = http_get("https://images-api.nasa.gov/search", params={"q": q, "media_type": "image,video",
                                                                   "page_size": 12})
        if not r.ok:
            return []
        hasil = []
        for it in r.json().get("collection", {}).get("items", []):
            d = (it.get("data") or [{}])[0]
            thumb = next((l["href"] for l in it.get("links", []) if l.get("render") == "image"), None)
            nid = d.get("nasa_id")
            if not nid or not thumb:
                continue
            video = d.get("media_type") == "video"
            dasar = thumb.rsplit("/", 1)[0]
            url = f"{dasar}/{nid}~medium.mp4" if video else re.sub(r"~(thumb|small|medium)\.jpg$", "~large.jpg", thumb)
            hasil.append({"id": f"nasa-{nid}", "sumber": "NASA", "jenis": "video" if video else "gambar", "url": url,
                          "thumb": thumb, "segmen": video,
                          "teks": f"{d.get('title', '')} {' '.join(d.get('keywords') or [])} {(d.get('description') or '')[:200]}",
                          "lebar": 0, "tinggi": 0, "lisensi": "NASA (public domain)",
                          "pembuat": d.get("photographer") or d.get("center") or "NASA",
                          "halaman": f"https://images.nasa.gov/details/{nid}", "judul": d.get("title", "")})
        return hasil
    return _cache(f"nasa|{q}", f)


# Hanya koleksi lembaga yang memang public domain. Item "community" yang ditandai PD oleh pengunggahnya sering
# berupa unggahan ulang dokumenter berhak cipta, jadi tidak dipakai.
KOLEKSI_ARSIP = {
    "prelinger": ("Public Domain (Prelinger Archives)", "Prelinger Archives"),
    "FedFlix": ("Public Domain (film pemerintah AS)", "FedFlix / US Government"),
    "usnationalarchives": ("Public Domain (US National Archives)", "US National Archives"),
    "UniversalNewsreels": ("Public Domain (Universal Newsreels, US National Archives)", "Universal Newsreels"),
    "nasa": ("NASA (public domain)", "NASA"),
}


def archive(q):
    """Film arsip public domain dari koleksi lembaga (Prelinger, FedFlix, National Archives, NASA)."""
    def f():
        bersih = re.sub(r"[^\w\s'-]", " ", q).strip()
        r = http_get("https://archive.org/advancedsearch.php", params={
            "q": f"({bersih}) AND mediatype:movies AND collection:({' OR '.join(KOLEKSI_ARSIP)})",
            "fl[]": ["identifier", "title", "description", "collection"], "rows": 12, "output": "json"})
        if not r.ok:
            return []
        hasil = []
        for d in r.json().get("response", {}).get("docs", []):
            judul = d.get("title") or ""
            judul = " ".join(judul) if isinstance(judul, list) else judul
            if ARSIP_BUANG.search(judul) or BERITA.search(judul):
                continue
            desk = d.get("description") or ""
            desk = " ".join(desk) if isinstance(desk, list) else desk
            koleksi = d.get("collection") or []
            koleksi = koleksi if isinstance(koleksi, list) else [koleksi]
            asal = next((KOLEKSI_ARSIP[c] for c in KOLEKSI_ARSIP if c in koleksi), None)
            if not asal:
                continue
            hasil.append({"id": f"ia-{d['identifier']}", "sumber": "Archive.org", "jenis": "video", "url": None,
                          "ia_id": d["identifier"], "thumb": f"https://archive.org/services/img/{d['identifier']}",
                          "segmen": True, "teks": f"{judul} {_bersih_html(desk)[:300]}",
                          "lebar": 640, "tinggi": 480, "lisensi": asal[0], "pembuat": asal[1],
                          "halaman": f"https://archive.org/details/{d['identifier']}", "judul": judul})
        return hasil[:8]
    return _cache(f"ia3|{q}", f)


def _thumb_wikimedia(url, lebar=0, maks=1920):
    """File asli di upload.wikimedia.org (sering puluhan MB) ditolak 429 kalau diambil langsung.
    Ubah ke URL thumbnail resmi, misal .../thumb/a/ab/Nama.jpg/1920px-Nama.jpg."""
    t = re.match(r"^(https://[a-z]+\.wikimedia\.org/wikipedia/commons/thumb/.+/)(\d+)px-([^/?#]+)", url or "")
    if t:  # sudah URL thumbnail: cukup kecilkan lebarnya
        return f"{t.group(1)}{min(int(t.group(2)), maks)}px-{t.group(3)}"
    m = re.match(r"^https://upload\.wikimedia\.org/wikipedia/commons/([0-9a-f])/([0-9a-f]{2})/([^/?#]+)", url or "")
    if not m:
        return url
    nama = m.group(3)
    ekor = nama.lower().rsplit(".", 1)[-1]
    raster = ekor in ("jpg", "jpeg", "png", "gif", "webp")
    # Thumbnail selebar/lebih lebar dari aslinya ditolak (400); gambar yang sudah kecil pakai file aslinya saja.
    if raster and lebar and int(lebar) <= maks:
        return url
    tambahan = "" if raster else (".png" if ekor == "svg" else ".jpg")
    lebar = maks if lebar else min(maks, 1280)
    return (f"https://upload.wikimedia.org/wikipedia/commons/thumb/{m.group(1)}/{m.group(2)}/{nama}/"
            f"{lebar}px-{nama}{tambahan}")


def _unduh_wikimedia(url, tujuan, lebar=0, maks=1920, batas_mb=40, batal=None):
    """Coba thumbnail dulu; kalau ditolak (misalnya lebar asli tidak diketahui dan ternyata lebih kecil),
    ambil file aslinya."""
    kecil = _thumb_wikimedia(url, lebar, maks)
    return unduh(kecil, tujuan, batas_mb=batas_mb, batal=batal) or \
        (unduh(url, tujuan, batas_mb=batas_mb, batal=batal) if kecil != url else None)


def _flickr_besar(url):
    """URL Flickr 500px dari Openverse → versi 1024px (_b)."""
    m = re.match(r"^(https://live\.staticflickr\.com/\d+/\d+_[0-9a-f]+)(_[a-z])?\.jpg$", url or "")
    return f"{m.group(1)}_b.jpg" if m else url


def openverse(q):
    """Foto berlisensi bebas (boleh komersial & diubah) dari Flickr, museum, dsb. Tanpa login."""
    if time.time() < _openverse_habis:
        return []

    def f():
        global _openverse_habis
        r = http_get("https://api.openverse.org/v1/images/", params={
            "q": q, "license_type": "commercial,modification", "page_size": 12, "mature": "false"})
        if r.status_code == 429:
            _openverse_habis = time.time() + 3600
            raise RuntimeError("batas pencarian Openverse hari ini habis, dilewati dulu")
        if not r.ok:
            return []
        hasil = []
        for d in r.json().get("results", []):
            if not d.get("url"):
                continue
            lisensi = f"CC {d.get('license', '').upper()} {d.get('license_version') or ''}".strip()
            if d.get("license") in ("pdm", "cc0"):
                lisensi = "Public Domain" if d["license"] == "pdm" else "CC0"
            hasil.append({"id": f"ov-{d['id']}", "sumber": "Openverse", "jenis": "gambar",
                          # Thumbnail langsung dari penyedia: proxy thumbnail Openverse ikut memakan jatah harian.
                          "url": _thumb_wikimedia(_flickr_besar(d["url"]), d.get("width")),
                          "thumb": _thumb_wikimedia(d["url"], d.get("width"), maks=480),
                          "teks": f"{d.get('title') or ''} {' '.join(t.get('name', '') for t in d.get('tags') or [])}",
                          "lebar": d.get("width") or 0, "tinggi": d.get("height") or 0, "lisensi": lisensi,
                          "pembuat": d.get("creator") or "", "halaman": d.get("foreign_landing_url"),
                          "judul": d.get("title") or ""})
        return hasil
    return _cache(f"ov2|{q}", f)


def met(q):
    """The Met: lukisan, ukiran, peta, artefak public domain."""
    def f():
        r = http_get("https://collectionapi.metmuseum.org/public/collection/v1.1/search",
                     params={"q": q, "hasImages": "true", "limit": 8})
        if not r.ok:
            return []
        hasil = []
        for oid in (r.json().get("objectIDs") or [])[:6]:
            o = http_get(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}")
            if not o.ok:
                continue
            d = o.json()
            if not d.get("isPublicDomain") or not d.get("primaryImage"):
                continue
            tags = " ".join(t.get("term", "") for t in d.get("tags") or [])
            hasil.append({"id": f"met-{oid}", "sumber": "The Met", "jenis": "gambar", "url": d["primaryImage"],
                          "thumb": d.get("primaryImageSmall") or d["primaryImage"],
                          "teks": f"{d.get('title', '')} {tags} {d.get('objectName', '')}",
                          "lebar": 0, "tinggi": 0, "lisensi": "Public Domain (CC0)",
                          "pembuat": d.get("artistDisplayName") or "The Metropolitan Museum of Art",
                          "halaman": d.get("objectURL"), "judul": d.get("title", "")})
        return hasil
    return _cache(f"met|{q}", f)


def cleveland(q):
    """Cleveland Museum of Art Open Access (CC0)."""
    def f():
        r = http_get("https://openaccess-api.clevelandart.org/api/artworks/",
                     params={"q": q, "has_image": 1, "cc0": 1, "limit": 8})
        if not r.ok:
            return []
        hasil = []
        for d in r.json().get("data", []):
            img = d.get("images") or {}
            besar = img.get("print") or img.get("full") or img.get("web") or {}
            if not besar.get("url"):
                continue
            pembuat = ", ".join(c.get("description", "") for c in d.get("creators") or [])[:80]
            hasil.append({"id": f"cma-{d['id']}", "sumber": "Cleveland Museum", "jenis": "gambar",
                          "url": besar["url"], "thumb": (img.get("web") or besar)["url"],
                          "teks": f"{d.get('title', '')} {d.get('type', '')} {(d.get('description') or '')[:200]}",
                          "lebar": int(besar.get("width") or 0), "tinggi": int(besar.get("height") or 0),
                          "lisensi": "CC0", "pembuat": pembuat or "Cleveland Museum of Art",
                          "halaman": d.get("url"), "judul": d.get("title", "")})
        return hasil
    return _cache(f"cma|{q}", f)


def wellcome(q):
    """Wellcome Collection: gravir, ilustrasi kuno, medis/anatomi. Tanpa login; hanya domain publik / CC0 / CC BY."""
    def f():
        r = http_get("https://api.wellcomecollection.org/catalogue/v2/images", params={"query": q, "pageSize": 12})
        if not r.ok:
            return []
        hasil = []
        for im in r.json().get("results", []):
            loc = (im.get("locations") or [{}])[0]
            lis = (loc.get("license") or {}).get("id", "")
            if lis not in ("pdm", "cc-0", "cc-by") or not str(loc.get("url", "")).endswith("/info.json"):
                continue
            dasar = loc["url"][:-len("/info.json")]
            src = im.get("source") or {}
            judul = " ".join(str(src.get("title") or "").split())
            hasil.append({"id": f"wellcome-{im['id']}", "sumber": "Wellcome Collection", "jenis": "gambar",
                          "url": f"{dasar}/full/!1920,1920/0/default.jpg",
                          "thumb": f"{dasar}/full/!600,600/0/default.jpg",
                          "teks": judul, "lebar": 0, "tinggi": 0,
                          "lisensi": {"pdm": "Public Domain Mark", "cc-0": "CC0", "cc-by": "CC BY 4.0"}[lis],
                          "pembuat": "Wellcome Collection",
                          "halaman": f"https://wellcomecollection.org/works/{src.get('id', '')}", "judul": judul})
        return hasil
    return _cache(f"wellcome|{q}", f)


def europeana(q):
    """Europeana: koleksi ribuan museum & perpustakaan Eropa, hanya lisensi terbuka (reusability=open: domain
    publik, CC0, CC BY, CC BY-SA). "api2demo" adalah kunci demo publik dari Europeana sendiri (tanpa daftar)."""
    def f():
        r = http_get("https://api.europeana.eu/record/v2/search.json", params={
            "wskey": "api2demo", "query": q, "reusability": "open", "media": "true", "qf": "TYPE:IMAGE",
            "rows": 12})
        if not r.ok:
            return []
        hasil = []
        for it in r.json().get("items", []):
            penuh, kecil = (it.get("edmIsShownBy") or [""])[0], (it.get("edmPreview") or [""])[0]
            if not penuh or not kecil:
                continue
            hak = (it.get("rights") or [""])[0]
            lisensi = ("Public Domain" if "publicdomain" in hak else "CC BY-SA" if "by-sa" in hak
                       else "CC BY" if "/by/" in hak else hak or "lihat halaman")
            judul = " ".join(str((it.get("title") or [""])[0]).split())[:150]
            hasil.append({"id": "europeana-" + str(it.get("id", "")).strip("/").replace("/", "-"),
                          "sumber": "Europeana", "jenis": "gambar", "url": penuh, "thumb": kecil,
                          "teks": judul + " " + " ".join(it.get("dcDescription") or [])[:200],
                          "lebar": 0, "tinggi": 0, "lisensi": lisensi,
                          "pembuat": str((it.get("dataProvider") or ["Europeana"])[0])[:80],
                          "halaman": it.get("guid"), "judul": judul})
        return hasil
    return _cache(f"europeana|{q}", f)


EDGE = peramban()  # Edge di Windows; Chromium/Chrome di Linux ("" = tidak ada)
# Foto stok ber-watermark dan media sosial yang butuh login: tidak dipakai.
_WEB_LEWAT = re.compile(r"alamy|dreamstime|shutterstock|gettyimages|istockphoto|123rf|depositphotos|stock\.adobe|"
                        r"adobestock|vecteezy|freepik|canstockphoto|bigstock|pond5|agefotostock|facebook|fbcdn|"
                        r"instagram|tiktok|youtube|ytimg|//x\.com|twitter|threads\.net|lookaside", re.I)
_edge_kunci = threading.Semaphore(2)  # maksimal 2 Edge headless bersamaan


def web_bing(q, lisensi=False):
    """Gambar dari SELURUH web lewat Bing Images, dibuka di Edge headless (diminta pengguna: "scraping internet
    selama free"). Tiap kueri memakai profil browser baru — dengan profil yang sama, kueri kedua dan seterusnya
    diberi hasil acak (kue keju untuk "situs Gunung Padang"). lisensi=True: filter Bing "bebas diubah, dibagikan,
    dan dipakai komersial". Tanpa filter, hak cipta gambar milik pemiliknya masing-masing."""
    if not EDGE:
        return []

    def f():
        params = {"q": q, "form": "HDRSC2", "first": 1}
        if lisensi:
            params["qft"] = "+filterui:license-L2_L3_L5"
        url = "https://www.bing.com/images/search?" + urlencode(params)
        with _edge_kunci, tempfile.TemporaryDirectory(dir=str(CACHE), ignore_cleanup_errors=True) as profil:
            out = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                                  "--no-default-browser-check", f"--user-data-dir={profil}",
                                  "--virtual-time-budget=8000", "--dump-dom", url],
                                 capture_output=True, timeout=90)
        hasil = []
        for mentah in re.findall(r' m="(\{&quot;[^"]+\})"', out.stdout.decode("utf-8", "ignore")):
            try:
                d = json.loads(html.unescape(mentah))
            except ValueError:
                continue
            murl, purl = d.get("murl") or "", d.get("purl") or ""
            if not murl.startswith("http") or _WEB_LEWAT.search(f"{murl} {purl}"):
                continue
            judul = " ".join(str(d.get("t") or "").split())[:150]
            situs = re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", purl)
            hasil.append({"id": "web-" + hash_pendek(murl), "sumber": "Web", "jenis": "gambar", "url": murl,
                          "thumb": d.get("turl") or murl, "halaman": purl, "referer": purl, "judul": judul,
                          "teks": f"{judul} {d.get('desc') or ''}"[:300], "lebar": 0, "tinggi": 0,
                          "lisensi": "bebas dipakai menurut filter Bing" if lisensi else "hak cipta milik pemiliknya",
                          "pembuat": situs})
            if len(hasil) >= 16:
                break
        return hasil
    return _cache(f"bing{'L' if lisensi else ''}|{q}", f)


BUKAN_FOTO = re.compile(r"logo|icon|ikon|flag[ _]of|bendera|symbol|commons-|wiki|question[ _]book|edit-|ambox|"
                        r"padlock|nuvola|crystal[ _]clear|gnome|disambig|portal|location[ _]map|locator|"
                        r"signature|tanda[ _]tangan|\.svg$|\.gif$|\.pdf$|\.djvu$|audio|\.ogg$|\.oga$", re.I)


def _info_commons(judul_file):
    """imageinfo untuk ≤50 file Commons sekaligus → kandidat foto (bukan logo/ikon/peta lokasi)."""
    hasil = []
    for mulai in range(0, len(judul_file), 50):
        r = http_get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "titles": "|".join(judul_file[mulai:mulai + 50]),
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920,
            "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription"})
        if not r.ok:
            continue
        for p in (r.json().get("query", {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            judul = p.get("title", "").replace("File:", "")
            if not ii.get("url") or BUKAN_FOTO.search(judul) or ii.get("mime") not in (
                    "image/jpeg", "image/png", "image/tiff", "image/webp") or (ii.get("width") or 0) < 500:
                continue
            em = ii.get("extmetadata", {})
            judul_bersih = re.sub(r"\.\w+$", "", judul).replace("_", " ")
            hasil.append({"id": f"wiki-{p.get('pageid')}", "sumber": "Wikimedia", "jenis": "gambar",
                          "url": ii.get("thumburl") or ii["url"], "thumb": ii.get("thumburl"), "topik": True,
                          "teks": judul_bersih + " " + _bersih_html(em.get("ImageDescription", {}).get("value"))[:200],
                          "lebar": ii.get("width", 0), "tinggi": ii.get("height", 0),
                          "lisensi": _bersih_html(em.get("LicenseShortName", {}).get("value")) or "lihat halaman",
                          "pembuat": _bersih_html(em.get("Artist", {}).get("value"))[:80],
                          "halaman": ii.get("descriptionurl"), "judul": judul_bersih})
    return hasil


def _file_kategori(kategori, batas=150, kedalaman=2):
    """File di kategori Commons dan subkategorinya (sampai 2 tingkat, maksimal 30 kategori)."""
    files, antre, lihat = [], [(kategori, 0)], set()
    while antre and len(files) < batas:
        kat, tingkat = antre.pop(0)
        if kat in lihat:
            continue
        lihat.add(kat)
        c = http_get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "list": "categorymembers", "cmtitle": f"Category:{kat}",
            "cmtype": "file|subcat", "cmlimit": 100})
        for x in (c.json().get("query", {}).get("categorymembers") or []) if c.ok else []:
            if x.get("ns") == 14 and tingkat < kedalaman and len(lihat) + len(antre) < 30:
                antre.append((x["title"].split(":", 1)[1], tingkat + 1))
            elif x.get("ns") == 6:
                files.append(x["title"])
    return files[:batas]


def gambar_artikel(lang, judul, log=print):
    """Gambar di satu artikel Wikipedia + isi kategori Commons-nya (Wikidata P373). Dipakai untuk topik utama dan
    untuk adegan yang membahas satu bukti tertentu (misalnya artikel "Bixi" untuk adegan kura-kura batu)."""
    def ambil():
        api = f"https://{lang}.wikipedia.org/w/api.php"
        r = http_get(api, params={"action": "query", "format": "json", "titles": judul, "redirects": 1,
                                  "prop": "images|pageprops", "imlimit": 80, "ppprop": "wikibase_item"})
        halaman = next(iter((r.json().get("query", {}).get("pages") or {}).values()), {}) if r.ok else {}
        file_artikel = [x["title"].replace("Berkas:", "File:") for x in halaman.get("images", [])]
        file_depicts, file_kategori = [], []
        qid = (halaman.get("pageprops") or {}).get("wikibase_item")
        if qid:
            # Foto yang di Commons ditandai "menggambarkan" (P180) item ini: paling pasti isinya benda itu.
            d = http_get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "list": "search", "srnamespace": 6, "srlimit": 50,
                "srsearch": f"haswbstatement:P180={qid}"})
            file_depicts = [x["title"] for x in (d.json().get("query", {}).get("search") or [])] if d.ok else []
            # kategori Commons dari Wikidata (properti P373), termasuk subkategori ("Bixi by city" → ratusan foto)
            w = http_get("https://www.wikidata.org/w/api.php", params={
                "action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"})
            klaim = (w.json().get("entities", {}).get(qid, {}).get("claims", {}).get("P373") or []) if w.ok else []
            kategori = klaim[0]["mainsnak"]["datavalue"]["value"] if klaim else ""
            if kategori:
                file_kategori = _file_kategori(kategori)
        judul_file = list(dict.fromkeys(file_artikel + file_depicts + file_kategori))
        return _info_commons(judul_file) if judul_file else []

    try:
        hasil = _cache(f"topik2|{lang}|{judul}", ambil, umur_hari=30)
    except Exception as e:
        log(f"  Gambar dari artikel Wikipedia {lang} “{judul}” gagal: {e}")
        return []
    return [{**k, "topik": True, "kueri": judul, "artikel": judul} for k in hasil]


def gambar_topik(sumber_riset, log=print):
    """Gambar yang PASTI nyambung dengan topik video: gambar di artikel Wikipedia topiknya + isi kategori
    Commons-nya (misalnya kategori "Loch Ness Monster": foto Surgeon 1934, ilustrasi, patung), ditambah
    ilustrasi/lukisan subjeknya dari Openverse. Dipakai di setiap adegan, AI yang memilih mana yang cocok."""
    semua, lihat = [], set()

    def tambah(daftar, kueri):
        for k in daftar:
            if k["id"] not in lihat:
                lihat.add(k["id"])
                semua.append({**k, "topik": True, "kueri": kueri})

    # hanya artikel UTAMA (en/id), bukan artikel terkait: video bulan tanpa artikel Indonesia pernah mengambil artikel
    # "Lunar Reconnaissance Orbiter" sebagai topik, lalu ratusan foto perangkat satelit membanjiri semua adegan
    for s in [x for x in sumber_riset if not x.get("terkait")][:2]:
        if s.get("judul"):
            tambah(gambar_artikel(s.get("lang", "en"), s["judul"], log), s["judul"])

    subjek = next((s["judul"] for s in sumber_riset if s.get("lang") == "en"), "") or \
        (sumber_riset[0]["judul"] if sumber_riset else "")
    if subjek:
        for q in (f"{subjek} illustration", f"{subjek} painting"):
            try:
                tambah(openverse(q), subjek)
            except Exception as e:
                log(f"  Openverse “{q}” gagal: {e}")
    log(f"Gambar topik: {len(semua)} gambar dari artikel Wikipedia, kategori Commons, dan ilustrasi “{subjek}”")
    return semua


def cari_kandidat(cfg, q_a, q_b, format_video, log=print, q_c="", video=False):
    """q_a = hal spesifik, q_b = visual umum, q_c = ilustrasi/arsip/peta lama.
    video=True (tata visual "video + stiker"): klip video dicari dari semua sumber video untuk kata kunci a DAN b,
    karena video jadi latar hampir semua shot, sedangkan foto yang tepat ditempel sebagai stiker."""
    orient = "portrait" if format_video == "9:16" else "landscape"
    ada_stok = cfg.get("pexels_key") or cfg.get("pixabay_key")
    tugas = []
    if video:
        for q in dict.fromkeys(x for x in (q_b, q_a) if x):
            tugas += [("Mixkit", q, lambda q=q: mixkit(q))]
        if q_b:
            tugas += [("Wikimedia video", q_b, lambda: wikimedia(q_b, "video"))]
            if ada_stok:  # tanpa Pexels/Pixabay, Archive.org untuk kata kunci b sudah dicari di bawah
                tugas += [("Archive.org", q_b, lambda: archive(q_b))]
    web = cfg.get("sumber_web", "tidak")
    # Gambar dari seluruh web (Bing via Edge headless). Filter lisensi Bing hasilnya sering tidak nyambung (figurin
    # kura-kura di eBay untuk "Bixi"), jadi mode "semua" cukup memakai pencarian biasa.
    if q_a and web == "berlisensi":
        tugas += [("Web berlisensi", q_a, lambda: web_bing(q_a, lisensi=True))]
    elif q_a and web == "semua":
        tugas += [("Web", q_a, lambda: web_bing(q_a))]
    if q_a:
        tugas += [("Wikimedia", q_a, lambda: wikimedia(q_a)), ("NASA", q_a, lambda: nasa(q_a)),
                  ("Wikimedia video", q_a, lambda: wikimedia(q_a, "video")), ("Archive.org", q_a, lambda: archive(q_a))]
        if not q_c:
            tugas += [("Openverse", q_a, lambda: openverse(q_a))]
        tugas += [("Europeana", q_a, lambda: europeana(q_a))]
        # klip video stok untuk hal spesifiknya juga (hewan, tempat): "chicken", "ostrich" di Pexels/Pixabay jauh
        # lebih hidup daripada foto; yang tidak nyambung (misalnya "Apollo 11") disaring juri AI
        if cfg.get("pexels_key"):
            tugas += [("Pexels video", q_a, lambda: pexels_video(q_a, orient, cfg["pexels_key"]))]
        if cfg.get("pixabay_key"):
            tugas += [("Pixabay video", q_a, lambda: pixabay_video(q_a, cfg["pixabay_key"]))]
    if q_c:
        tugas += [("Openverse", q_c, lambda: openverse(q_c)), ("The Met", q_c, lambda: met(q_c)),
                  ("Cleveland Museum", q_c, lambda: cleveland(q_c)), ("Wikimedia", q_c, lambda: wikimedia(q_c)),
                  ("Wellcome Collection", q_c, lambda: wellcome(q_c)), ("Europeana", q_c, lambda: europeana(q_c))]
    if q_b:
        if cfg.get("pexels_key"):
            tugas += [("Pexels video", q_b, lambda: pexels_video(q_b, orient, cfg["pexels_key"])),
                      ("Pexels foto", q_b, lambda: pexels_foto(q_b, orient, cfg["pexels_key"]))]
        if cfg.get("pixabay_key"):
            tugas += [("Pixabay video", q_b, lambda: pixabay_video(q_b, cfg["pixabay_key"])),
                      ("Pixabay foto", q_b, lambda: pixabay_foto(q_b, orient, cfg["pixabay_key"]))]
        if not ada_stok:
            tugas += [("Openverse", q_b, lambda: openverse(q_b)), ("Wikimedia", q_b, lambda: wikimedia(q_b)),
                      ("Archive.org", q_b, lambda: archive(q_b))]
    # Semua sumber dicari bersamaan (menunggu jaringan, bukan CPU); urutan hasil tetap mengikuti daftar tugas.
    def jalankan_satu(tugas_ini):
        nama, kueri, fn = tugas_ini
        try:
            return [{**k, "kueri": kueri} for k in fn()]
        except Exception as e:
            log(f"  {nama} gagal: {e}")
            return []

    with ThreadPoolExecutor(max_workers=6) as kolam:
        hasil_per_tugas = list(kolam.map(jalankan_satu, tugas))
    semua, lihat = [], set()
    for hasil in hasil_per_tugas:
        for k in hasil:
            if k["id"] not in lihat:
                lihat.add(k["id"])
                semua.append(k)
    return semua


# ---------------------------------------------------------------- penilaian

def identitas(k):
    """Kunci "gambar yang sama". File Wikimedia yang sama bisa muncul dari pencarian Commons, artikel
    Wikipedia, dan Openverse dengan id berbeda; tanpa ini peta yang sama bisa tampil dua shot berturut-turut."""
    url = unquote(k.get("url") or "")
    m = re.search(r"wikimedia\.org/wikipedia/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?#]+)", url)
    if m:
        return "commons:" + m.group(1).lower().replace(" ", "_")
    return k.get("id", "")


_fitur_cache = {}


def _fitur(k):
    """Titik fitur ORB dari thumbnail (disimpan di memori per kandidat)."""
    if k["id"] in _fitur_cache:
        return _fitur_cache[k["id"]]
    hasil = None
    try:
        import cv2
        import numpy as np
        t = thumb_lokal(k) if not k.get("file") else None
        if t:
            img = cv2.imdecode(np.fromfile(str(t), np.uint8), cv2.IMREAD_GRAYSCALE)  # path Windows ber-spasi
            if img is not None:
                kp, des = cv2.ORB_create(800).detectAndCompute(img, None)
                if des is not None and len(des) >= 20:
                    hasil = (np.float32([x.pt for x in kp]), des)
    except Exception:
        hasil = None
    _fitur_cache[k["id"]] = hasil
    return hasil


def suasana(k):
    """0..1: seberapa "misterius" suasana gambarnya (gelap, kelam, atau hitam-putih seperti foto arsip).
    Dipakai untuk mendahulukan gambar bernuansa misteri di antara gambar yang sama-sama cocok."""
    if "suasana" in k:
        return k["suasana"]
    nilai = 0.0
    try:
        import cv2
        import numpy as np
        t = thumb_lokal(k) if not k.get("file") else None
        img = cv2.imdecode(np.fromfile(str(t), np.uint8), cv2.IMREAD_COLOR) if t else None
        if img is not None:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            terang, jenuh = float(hsv[..., 2].mean()), float(hsv[..., 1].mean())
            nilai = 0.6 * min(1, max(0, (170 - terang) / 120)) + 0.4 * min(1, max(0, (140 - jenuh) / 140))
    except Exception:
        pass
    k["suasana"] = round(nilai, 3)
    return k["suasana"]


def sama_gambar(k1, k2):
    """True kalau dua kandidat sebenarnya foto yang sama (juga versi crop/resize dari sumber berbeda).
    Diuji pada foto Apollo: foto Aldrin asli vs versi crop = 278 titik cocok; foto berbeda paling banyak 7."""
    a, b = _fitur(k1), _fitur(k2)
    if not a or not b:
        return False
    try:
        import cv2
        cocok = [m for m, n in (x for x in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(a[1], b[1], k=2) if len(x) == 2)
                 if m.distance < 0.75 * n.distance]
        if len(cocok) < 30:
            return False
        _, mask = cv2.findHomography(a[0][[m.queryIdx for m in cocok]], b[0][[m.trainIdx for m in cocok]],
                                     cv2.RANSAC, 5.0)
        return mask is not None and int(mask.sum()) >= 30
    except Exception:
        return False


def nilai_heuristik(k, format_video, terpakai, subjek=(), video=False):
    q = set(_kata(k.get("kueri")))
    t = set(_kata(k.get("teks")))
    cocok = len(q & t) / len(q) if q else 0
    skor = cocok * 3 + PRIOR.get(k["sumber"], 0)
    if subjek and set(subjek) & t:
        skor += 1.0  # judul/teks gambar menyebut subjek video (misal "Loch Ness Monster 01")
    if k.get("topik"):
        skor += 1.2  # dari artikel/kategori topik: hampir pasti nyambung
    if k["jenis"] == "video":
        skor += 2.0 if video else 0.8
    w, h = k.get("lebar") or 0, k.get("tinggi") or 0
    if w and h:
        tegak = h > w
        if tegak == (format_video == "9:16"):
            skor += 0.6
        pendek = min(w, h)
        skor += 0.5 if pendek >= 1080 else 0.2 if pendek >= 720 else -0.8
    if identitas(k) in terpakai:
        skor -= 4
    return round(skor, 3)


def thumb_lokal(k):
    """Unduh thumbnail kecil (dipakai AI untuk melihat & ditampilkan di GUI). Kandidat yang bendanya sudah dipotong
    dari latar (stiker analogi) dilihat AI sebagai potongannya di atas latar abu terang — persis yang akan tampil."""
    if k.get("potongan") and Path(k["potongan"]).exists():
        tujuan = F_THUMB / f"potong-{hash_pendek(k['potongan'])}.jpg"
        if not tujuan.exists():
            from PIL import Image
            im = Image.open(k["potongan"])
            im.thumbnail((512, 512))
            latar = Image.new("RGB", im.size, (232, 232, 232))
            latar.paste(im, (0, 0), im)
            latar.save(tujuan, quality=88)
        return tujuan
    tujuan = F_THUMB / f"{hash_pendek(k['id'])}.jpg"
    if tujuan.exists():
        return tujuan
    if not k.get("thumb"):
        return None
    mentah = _unduh_wikimedia(k["thumb"], F_THUMB / f"{hash_pendek(k['id'])}.raw", maks=480, batas_mb=15)
    if not mentah:
        return None
    try:
        ffmpeg(["-i", str(mentah), "-frames:v", "1", "-vf", "scale='min(512,iw)':-2", "-q:v", "4", str(tujuan)],
               timeout=60)
    except RuntimeError:
        return None
    finally:
        mentah.unlink(missing_ok=True)
    return tujuan


SCHEMA_SKOR = {
    "type": "object",
    "properties": {"foto": {"type": "array", "items": {
        "type": "object",
        "properties": {"no": {"type": "integer"}, "isi": {"type": "string"}, "subjek": {"type": "integer"},
                       "detail": {"type": "integer"}},
        "required": ["no", "isi", "subjek", "detail"]}}},
    "required": ["foto"],
}
POSISI = ["kiri atas", "kanan atas", "kiri bawah", "kanan bawah"]
FONT_ANGKA = font_ffmpeg("arialbd")


# Foto yang bukan peristiwa/benda ASLINYA (dipakai juri AI dan perbandingan "satu foto, dua dunia").
_BUKAN_ASLI = re.compile(r"\b(training|exercises?|rehears\w*|simulat\w*|mock-?ups?|replicas?|dioramas?|latihan|"
                         r"berlatih|simulasi|replika|tiruan|maket)\b", re.I)


# Gambar amatir/tempelan: gemma menulis "pelukis membuat mural raksasa" lalu memberi 9.
_AMATIR = re.compile(r"\b(mural|murals|grafiti|graffiti|coretan|paint-by-numbers|poster|kartun|cartoons?|anime|"
                     r"mainan|toys?|figurine|kerajinan|crafts?|meme|screenshot|tangkapan layar|infografis|"
                     r"infographics?|ikon|icons?|clip-?art|vektor|vector|emoji|stiker|stickers?)\b", re.I)
# Kata umum yang tidak menentukan subjek ("foto X", "proses X", "lukisan X kuno").
_BUKAN_INTI = {"foto", "photo", "gambar", "image", "lukisan", "painting", "proses", "process", "visual", "suasana",
               "ilustrasi", "illustration", "yang", "dan", "atau", "dari", "the", "and", "kuno", "ancient", "besar",
               "big", "tua", "old", "misterius", "mysterious", "modern", "sangat", "sebuah", "with", "for", "video",
               "teori", "theory", "theories", "konspirasi", "conspiracy", "misteri", "mystery", "legenda", "legend"}


def batasi_skor(skor, isi, k, narasi="", lihat="", subjek="", alias=""):
    """Batas skor dari kode, karena gemma sering menulis isi foto dengan benar tapi tetap memberi skor tinggi:
    - foto latihan/simulasi/replika (padahal adegannya tentang peristiwa aslinya): maksimal 4;
    - mural, poster, kartun, mainan, tangkapan layar: maksimal 3;
    - SUBJEK adegan tidak disebut sama sekali di judul file, keterangan, maupun isi menurut AI ("batang kayu fosil"
      untuk subjek "raksasa membatu"): maksimal 6 — hanya setema, bukan tepat. Gambar topik dari artikel Wikipedia
      dihitung menyebut nama artikelnya; `alias` = nama artikel bukti adegan itu ("Rujm el-Hiri" untuk subjek
      "Wheel of Giants", "Gunung Padang" untuk "punden berundak")."""
    adegan = f"{narasi} {lihat} {subjek}"
    teks = f"{isi} {k.get('judul') or ''} {k.get('teks') or ''}"
    if _BUKAN_ASLI.search(teks) and not _BUKAN_ASLI.search(adegan):
        skor = min(skor, 4)
    if _AMATIR.search(f"{isi} {k.get('judul') or ''}") and not _AMATIR.search(adegan):
        skor = min(skor, 3)
    inti = [w for w in re.findall(r"\w+", (subjek or "").lower()) if len(w) >= 3 and w not in _BUKAN_INTI]
    if inti and alias:
        inti += [w for w in re.findall(r"\w+", alias.lower()) if len(w) >= 3 and w not in _BUKAN_INTI]
    if inti and skor > 6:
        semua = f"{teks} {k.get('kueri') or '' if k.get('topik') else ''}".lower()
        if not any(w[:5] in semua for w in inti):
            skor = 6
    return skor


def nilai_ai(cfg, narasi, kandidat, batal=None, judul="", lihat="", subjek="", alias="", spesifik=True, latar=False,
             cerah=False):
    """AI (model vision) menilai 0-10 seberapa TEPAT tiap kandidat menampilkan "lihat" (apa yang harus tampak
    menurut narasi adegan). Dulu rubriknya "subjek video = skor tertinggi", jadi lukisan raksasa apa pun dapat 8-9
    padahal narasinya sedang membahas garam Himalaya atau patung Bixi.

    Thumbnail digabung jadi satu kolase 2x2 bernomor: gemma lebih akurat membandingkan satu kolase daripada
    beberapa gambar terpisah (urutannya sering tertukar), dan menyebut isi foto dulu membuat skornya masuk akal.
    latar=True (tata visual "video + stiker"): skor ketiga "latar" = seberapa pas sebagai LATAR suasana walaupun
    subjeknya tidak tampak (klip hutan berkabut untuk narasi Bigfoot), karena subjeknya ditempel sebagai stiker.
    Mengembalikan list [(skor, isi, latar | None) | None] sepanjang kandidat, atau None kalau gagal.
    """
    thumbs, idx = [], []
    for i, k in enumerate(kandidat[:4]):
        t = thumb_lokal(k)
        if t:
            thumbs.append(str(t))
            idx.append(i)
    if not thumbs:
        return None
    while len(thumbs) < 4:  # petak kosong
        thumbs.append(None)
    kolase = F_THUMB / f"kolase-{hash_pendek('|'.join(map(str, thumbs)))}.jpg"
    masukan, filter_ = [], ""
    for i, t in enumerate(thumbs):
        if t:
            masukan += ["-i", t]
        else:
            masukan += ["-f", "lavfi", "-i", "color=c=gray:s=448x448:d=1"]
        filter_ += (f"[{i}:v]scale=448:448:force_original_aspect_ratio=decrease,pad=448:448:(ow-iw)/2:(oh-ih)/2:"
                    f"color=gray,drawtext=fontfile='{FONT_ANGKA}':text='{i + 1}':x=12:y=8:fontsize=64:"
                    f"fontcolor=yellow:borderw=4:bordercolor=black[v{i}];")
    filter_ += "[v0][v1][v2][v3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0[o]"
    try:
        ffmpeg([*masukan, "-filter_complex", filter_, "-map", "[o]", "-frames:v", "1", "-q:v", "3", str(kolase)],
               timeout=60)
    except RuntimeError:
        return None
    n = len(idx)
    daftar = ", ".join(f"{i + 1} ({POSISI[i]})" for i in range(n))
    # judul file dari sumbernya: foto Phobos atau "Crew Training" terlihat mirip foto pendaratan Bulan, tapi judulnya
    # memberi tahu apa sebenarnya isi foto itu
    nama = "; ".join(f"{i + 1}) {' '.join(str(kandidat[j].get('judul') or '-').split())[:90]}"
                     for i, j in enumerate(idx))
    pesan = [{"role": "user", "images": [base64.b64encode(kolase.read_bytes()).decode()], "content": (
        f"Gambar ini kolase 2x2 berisi foto bernomor kuning: {daftar}. "
        + (f"Video ini tentang: {judul}. " if judul else "")
        + f"Itu calon visual latar untuk adegan dengan narasi:\n\"{narasi}\"\n"
        + f"SUBJEK UTAMA: {subjek or lihat or narasi}\nYANG HARUS TAMPAK: {lihat or narasi}\n"
        + f"Judul file dari sumbernya (bisa kurang akurat, foto web kadang judulnya judul halaman): {nama}\n\n"
        f"Untuk foto 1 sampai {n}: tulis isinya (maksimal 6 kata, sebut benda/tempat/makhluknya), lalu dua skor 0-10: "
        "\"subjek\" = seberapa jelas SUBJEK UTAMA tampak di foto itu (subjeknya sendiri, bukan sekadar benda yang "
        "mirip), dan \"detail\" = seberapa cocok dengan detail lain di YANG HARUS TAMPAK. Subjek jauh lebih penting: "
        "untuk \"raksasa yang membatu\", foto raksasa tanpa batu tetap bagus, foto batu tanpa raksasa jelek. "
        "Patokan skor subjek:\n"
        "- 9-10: persis menampilkan benda/tempat/makhluk/peristiwa yang disebut.\n"
        "- 7-8: jelas menampilkan hal yang sama atau sangat dekat (jenis benda yang sama, tempat yang sama).\n"
        "- 4-6: hanya SETEMA dengan video (misalnya lukisan raksasa lain, pemandangan atau suasana umum) tetapi "
        "bukan hal yang disebut.\n"
        "- 0-3: tidak nyambung.\n"
        "Benda/tempat LAIN yang hanya MIRIP (bulan atau planet lain, roket atau kendaraan lain, gunung atau situs "
        "lain, hewan lain) skor subjek maksimal 3 — perhatikan juga judul filenya. Kalau yang diminta peristiwa atau "
        "tempat ASLINYA, foto latihan, simulasi, replika, maket, diorama, atau pajangan museum tentang hal itu skor "
        "subjek maksimal 4 (kecuali YANG HARUS TAMPAK memang latihan/replika/museum). Untuk suasana abstrak "
        "(rahasia, misteri, pertanyaan), gambar yang memperlihatkan hal konkret dari topik videonya (arsip, "
        "dokumen, foto asli peristiwanya) lebih baik daripada gambar umum yang tidak menyinggung topiknya.\n"
        "Foto yang sebagian besar berisi TULISAN (poster, judul besar, infografis, tangkapan layar, halaman teks) "
        "atau ada watermark/nama situs di atas gambarnya: skor subjek maksimal 3, kecuali YANG HARUS TAMPAK memang "
        "dokumen atau tulisan. Turunkan skor untuk logo, diagram/peta yang tidak diminta, atau buram. Cuplikan "
        "berita TV, wawancara, tokoh politik, atau orang sungguhan yang tidak disebut: skor 0-2. Foto pribadi atau "
        "keluarga (bayi, anak, selfie, liburan, hewan peliharaan): skor subjek 0 walaupun ada patung/benda yang "
        "namanya mirip subjek. Karakter game/anime/kartun/fan-art: skor subjek 0. Gambar amatir, "
        "coretan anak, kerajinan, mainan, kartun, mural, atau papan nama toko/hotel: skor maksimal 3. Lukisan atau "
        "foto yang jelas memperlihatkan payudara atau alat kelamin, darah, atau kekerasan sadis: skor 0 (video bisa "
        "dibatasi umur di YouTube/TikTok); relief atau patung klasik yang tidak vulgar tetap boleh. Kalau dua "
        "foto sama tepatnya, beri skor sedikit lebih tinggi untuk yang "
        + ("terang, tajam, dan berwarna seperti foto dokumenter alam atau citra NASA." if cerah else
           "bernuansa misterius (gelap, berkabut, foto arsip hitam-putih, lukisan kuno).")
        + ("\nTambahkan skor ketiga \"latar\" 0-10 = seberapa cocok foto itu sebagai LATAR BERGERAK di belakang "
           "narasi tadi walaupun subjek utamanya tidak tampak (subjeknya nanti ditempel di atasnya sebagai stiker): "
           "7-10 tempat, benda, atau suasana yang jelas berhubungan dengan narasi (misalnya hutan berkabut untuk kisah "
           "Bigfoot, lautan gelap untuk kapal hilang, ruang arsip untuk dokumen rahasia); 4-6 suasana umum yang masih "
           "pas dengan nada videonya; 0-3 tidak nyambung, terlalu ceria, iklan atau produk, orang bicara ke kamera, "
           "atau penuh tulisan." if latar else ""))}]
    schema = SCHEMA_SKOR
    if latar:
        schema = json.loads(json.dumps(SCHEMA_SKOR))
        item = schema["properties"]["foto"]["items"]
        item["properties"]["latar"] = {"type": "integer"}
        item["required"].append("latar")
    try:
        j = ollama.chat_json(cfg, pesan, schema, batal=batal, maks_token=(48 if latar else 40) * n + 30, suhu=0.1)
    except (RuntimeError, ValueError):
        return None
    hasil = [None] * len(kandidat)
    for item in j.get("foto", []):
        try:
            no = int(item.get("no", 0)) - 1
            if 0 <= no < n:
                sub = max(0, min(10, int(item.get("subjek", item.get("skor", 0)))))
                det = max(0, min(10, int(item.get("detail", sub))))
                isi = str(item.get("isi", ""))[:60]
                # bobot subjek 70%; adegan abstrak (pertanyaan, "bukti disembunyikan") subjeknya hanya topik video,
                # jadi "yang harus tampak" ikut menentukan 50% — dulu gambar tata surya dapat 8 untuk "arsip rahasia"
                b = 0.7 if spesifik else 0.5
                skor = batasi_skor(round(b * sub + (1 - b) * det), isi, kandidat[idx[no]], narasi, lihat, subjek,
                                   alias)
                lat = None
                if latar:
                    lat = max(0, min(10, int(item.get("latar", 0))))
                    if _AMATIR.search(isi) or BERITA.search(isi):
                        lat = min(lat, 3)  # kartun/poster/cuplikan berita tetap tidak layak jadi latar
                hasil[idx[no]] = (skor, isi, lat)
        except (TypeError, ValueError):
            continue
    return hasil if any(hasil) else None


def cek_nalar(cfg, narasi, kandidat, batal=None, lihat="", subjek=""):
    """Pemeriksaan kedua TANPA gambar: deskripsi isi foto (tulisan juri AI sendiri) dicocokkan dengan narasi.
    Gemma menulis "Planet-planet di tata surya" lalu tetap memberi 8 untuk narasi "pendaratan asli atau rekayasa";
    ditanya lewat teks ("apakah gambar planet-planet memperlihatkan hal yang dibicarakan?") jawabannya jauh lebih
    masuk akal. Mengembalikan list bool (True = nyambung) sepanjang kandidat, atau None kalau gagal."""
    kandidat = kandidat[:6]
    if not kandidat:
        return []
    daftar = "\n".join(f"{i + 1}) {k.get('isi_ai') or '?'} (judul file: "
                        f"{' '.join(str(k.get('judul') or '-').split())[:80]})" for i, k in enumerate(kandidat))
    props = {f"cocok_{i + 1}": {"type": "boolean"} for i in range(len(kandidat))}
    pesan = [{"role": "user", "content": (
        f"Narasi adegan video: \"{narasi}\"\n"
        + (f"Subjek yang sedang dibicarakan: {subjek}\n" if subjek else "")
        + (f"Yang seharusnya tampak: {lihat}\n" if lihat else "")
        + f"\nCalon gambar latar (isi gambar menurut pengamat):\n{daftar}\n\n"
        "Untuk tiap gambar, cocok_N = true kalau penonton yang mendengar narasi itu sambil melihat gambar tersebut "
        "langsung paham hubungannya: gambar memperlihatkan subjek, benda, tempat, peristiwa, atau suasana yang "
        "sedang dibicarakan. false kalau hanya setema secara umum (misalnya sama-sama luar angkasa atau sama-sama "
        "batu), benda lain yang sekadar mirip, atau tidak nyambung.")}]
    try:
        j = ollama.chat_json(cfg, pesan, {"type": "object", "properties": props, "required": list(props)},
                             batal=batal, maks_token=12 * len(kandidat) + 30, suhu=0.1)
    except (RuntimeError, ValueError):
        return None
    return [bool(j.get(f"cocok_{i + 1}", True)) for i in range(len(kandidat))]


def cek_judul_latar(cfg, narasi, latar, kandidat, batal=None):
    """Klip yang tidak dilihat AI (cadangan / belum dinilai) hanya dikenal dari judulnya, jadi judulnya diperiksa
    model teks: apakah klip itu memperlihatkan tempatnya, bukan acara/orang/berita yang kebetulan memakai kata yang
    sama. Dulu "10th Mountain Division tests new technology" (tentara), "India Counts Cost of Disasters in Himalayas"
    (berita), dan "Complexity Science- 9 Earth Systems Science" (kuliah) lolos karena menyebut mountain/Himalayas/
    Earth. Mengembalikan list bool (True = cocok) sepanjang kandidat (maksimal 8), atau None kalau gagal."""
    kandidat = kandidat[:8]
    if not kandidat:
        return []
    daftar = "\n".join(f"{i + 1}) {' '.join(str(k.get('judul') or k.get('teks') or '-').split())[:100]}"
                       for i, k in enumerate(kandidat))
    props = {f"cocok_{i + 1}": {"type": "boolean"} for i in range(len(kandidat))}
    pesan = [{"role": "user", "content": (
        f"Narasi adegan video: \"{narasi}\"\n"
        + (f"Latar yang dicari: {latar}\n" if latar else "")
        + f"\nJudul klip stock video:\n{daftar}\n\n"
        "Untuk tiap judul, cocok_N = true kalau klip itu kemungkinan besar memperlihatkan pemandangan tempat yang "
        "dicari, atau benda/proses yang dibicarakan narasi, sehingga pas sebagai latar bergerak narasi itu. Tempat "
        "sejenis di negara lain boleh (gurun lain untuk gurun Sahara). false kalau judulnya menunjukkan fokus lain: "
        "orang atau kegiatan (tentara, turis, olahraga, ski, festival, pesta), berita, wawancara, kuliah atau "
        "presentasi, iklan, jenis tempat yang berbeda (pantai untuk gurun, kota untuk hutan), atau hanya kebetulan "
        "memakai kata yang sama.")}]
    try:
        j = ollama.chat_json(cfg, pesan, {"type": "object", "properties": props, "required": list(props)},
                             batal=batal, maks_token=12 * len(kandidat) + 30, suhu=0.1)
    except (RuntimeError, ValueError):
        return None
    return [bool(j.get(f"cocok_{i + 1}", True)) for i in range(len(kandidat))]


def _pilih_untuk_dilihat(kandidat, q, sudah, terpakai, jumlah=4, video=False):
    """Kandidat yang dikirim ke AI: campuran gambar topik dan tiap jenis kata kunci, bukan sekadar 4 skor
    kata tertinggi (dulu foto "Loch Ness Monster" kalah oleh "whale swimming" dan tidak pernah dilihat AI).
    video=True: tiap putaran 2 klip video (calon latar) + 2 foto (calon stiker)."""
    bebas = [k for k in kandidat if k["id"] not in sudah and identitas(k) not in terpakai]
    if video:
        klip = [k for k in bebas if k["jenis"] == "video"]
        # klip dari kata kunci berbeda dulu (suasana b + hal spesifik a), baru sisanya menurut skor kata
        klip = [x for kk in (q.get("b"), q.get("a")) for x in [k for k in klip if k.get("kueri") == kk][:1]] + klip
        foto = [k for k in bebas if k["jenis"] != "video"]
        foto = [k for k in foto if k.get("topik")][:1] + \
            [k for k in foto if not k.get("topik") and q.get("a") and k.get("kueri") == q.get("a")][:1] + foto
        lihat = []
        for k in klip:
            if sum(1 for x in lihat if x["jenis"] == "video") >= 2:
                break
            if k not in lihat:
                lihat.append(k)
        for k in foto + klip:  # sisa tempat: foto, lalu klip lagi kalau fotonya habis
            if len(lihat) >= jumlah:
                break
            if k not in lihat:
                lihat.append(k)
        return lihat
    kelompok = [
        [k for k in bebas if k.get("topik")][:2],
        [k for k in bebas if not k.get("topik") and q.get("a") and k.get("kueri") == q.get("a")][:1],
        [k for k in bebas if not k.get("topik") and q.get("c") and k.get("kueri") == q.get("c")][:1],
        [k for k in bebas if not k.get("topik") and k.get("kueri") == q.get("b")][:1],
        [k for k in bebas if k.get("sumber") == "Web"][:1],
    ]
    lihat = []
    for k in [x for g in kelompok for x in g] + bebas:  # sisanya diisi skor kata tertinggi
        if len(lihat) >= jumlah:
            break
        if k not in lihat:
            lihat.append(k)
    return lihat


SKOR_BAGUS = 7  # skor AI minimal supaya gambar dianggap tepat (rubrik: 4-6 = hanya setema)
LATAR_BAGUS = 5  # tata visual "video + stiker": klip minimal setema sudah layak jadi latar (subjeknya di stiker)
LATAR_JELAS = 7  # klip yang judul/isinya tidak menyebut subjeknya: tempatnya harus jelas berhubungan dengan narasi
# kata judul video yang tidak menunjuk subjek ("Kenapa Komodo Jadi Raksasa…" → komodo, raksasa, pulau)
_BUKAN_TOPIK = {"kenapa", "mengapa", "bagaimana", "apakah", "jadi", "bisa", "yang", "dari", "dalam", "dengan",
                "untuk", "adalah", "lebih", "paling", "ternyata", "sebenarnya", "rahasia", "misteri", "fakta", "dunia",
                "terjadi", "kalau", "sesuatu", "benar", "hanya", "tidak", "pernah", "selama", "sampai", "terus"}


def kata_topik(*teks):
    return {w for w in _kata(" ".join(teks)) if len(w) >= 4 and w not in _BUKAN_TOPIK}


def setopik(k, kata):
    """Judul/keterangan/isi klip menyebut subjek video atau adegan ("Varanus komodoensis", "Ausbreitung der
    Komodowarane")."""
    teks = _kata(f"{k.get('judul') or ''} {k.get('teks') or ''} {k.get('isi_ai') or ''}")
    return any(w.startswith(t) for w in teks for t in kata)


def nilai_latar(k):
    """Kelayakan klip sebagai latar bergerak. Klip yang tepat (≥7): skor latar dari AI atau skor tepatnya, mana yang
    lebih tinggi. Klip yang menyebut subjeknya: skor latarnya. Klip lain juga dari skor latarnya, tapi baru layak
    kalau tempatnya jelas berhubungan: dulu bola sepak di rumput (skor 6 "setema", latar 3), pria ber-headphone (6,
    latar 2), dan burung camar berburu ikan (6, latar 6) jadi latar narasi komodo karena diambil yang tertinggi."""
    lat = k.get("skor_latar")
    if lat is None or (k.get("skor_ai") or 0) >= SKOR_BAGUS:
        return max(k.get("skor_ai") or 0, lat or 0)
    # Judul menyebut subjeknya: cukup latar ≥ LATAR_BAGUS — tapi skor latar AI tetap berlaku. Dulu skor subjeknya
    # yang dipakai, jadi "Pottery Plate Shattering" (subjek 5, latar 3) jadi latar narasi lempeng ("plate") India.
    if k.get("setopik", True):
        return lat
    return lat if lat >= LATAR_JELAS else min(lat, LATAR_BAGUS - 1)


def urutkan_untuk_adegan(cfg, narasi, q, format_video, terpakai, cek_gambar, batal=None, log=print,
                         topik=(), judul="", butuh=1, lihat="", spesifik=True, subjek="", video=False, cerah=False):
    """Kandidat terurut (terbaik dulu). Yang teratas dipakai, sisanya cadangan untuk tombol Ganti.
    topik = gambar dari artikel/kategori topik video (lihat gambar_topik).
    video=True: tata visual "video + stiker" — `butuh` = jumlah klip latar; cukup satu foto tepat untuk stiker."""
    kandidat = cari_kandidat(cfg, q.get("a"), q.get("b"), format_video, log, q_c=q.get("c", ""), video=video)
    kandidat += [dict(k) for k in topik]
    unik, lihat_id = [], set()
    for k in kandidat:  # buang duplikat gambar yang sama dari sumber berbeda (versi topik didahulukan)
        kunci = identitas(k)
        if kunci in lihat_id:
            lama = next(x for x in unik if identitas(x) == kunci)
            lama["topik"] = lama.get("topik") or k.get("topik")
            continue
        lihat_id.add(kunci)
        unik.append(k)
    narasi_kecil = narasi.lower()

    def bukan_subjek(k):
        m = BUKAN_SUBJEK.search(f"{k.get('judul') or ''} {k.get('teks') or ''}")
        return bool(m) and m.group(0).lower() not in narasi_kecil  # kecuali narasinya memang membahas itu

    kandidat = [k for k in unik if not bukan_subjek(k) and not (cerah and arsip_tak_relevan(k, narasi))]
    # kata subjek VIDEO (untuk heuristik) — terpisah dari `subjek` ADEGAN yang dinilai AI. Dulu namanya sama, jadi
    # juri AI menerima "SUBJEK UTAMA: {'misteri', 'pendaratan', ...}" dan menilai cocok-tema, bukan cocok-adegan.
    kata_video = set(_kata(judul)) | set(_kata(" ".join(k.get("kueri", "") for k in topik[:1])))
    kata_subjek = kata_topik(judul, " ".join(k.get("kueri", "") for k in topik[:1]), subjek)
    for k in kandidat:
        k["skor_h"] = nilai_heuristik(k, format_video, terpakai, kata_video, video=video)
    kandidat.sort(key=lambda k: -k["skor_h"])
    if cek_gambar and kandidat:
        # nama lain subjek: artikel bukti adegan + artikel topik video (foto situs Gunung Padang tetap dihitung
        # menyebut subjek "punden berundak"/"tangga andesit")
        alias = " ".join(x for x in (q.get("artikel"), topik[0].get("kueri") if topik else "") if x)
        sudah = set()
        # Adegan yang membahas bukti/benda tertentu boleh dicari sampai 4 putaran; adegan abstrak (pertanyaan,
        # penghubung) cukup 2 putaran — tiap putaran ±1 menit dan yang setema pun sudah layak.
        # tiap putaran = satu panggilan AI vision (±1 menit di laptop ber-GPU, 2-3 menit di mini PC tanpa GPU);
        # setelan "putaran_gambar" membatasinya per mesin
        for putaran in range(int(cfg.get("putaran_gambar") or (3 if video else 4))):
            # adegan abstrak berhenti setelah 2 putaran, KECUALI belum ada satu pun gambar yang layak (≥5)
            # (yang dihitung hanya gambar yang belum tampil di adegan lain: dulu gambar layak yang sudah terpakai
            # menghentikan pencarian, lalu adegan "29 hektar" jatuh ke foto kastil yang belum dinilai)
            if putaran >= 2 and not spesifik and not video and any(
                    (k.get("skor_ai") or 0) >= 5 and identitas(k) not in terpakai for k in kandidat):
                break
            dilihat = _pilih_untuk_dilihat(kandidat, q, sudah, terpakai, video=video)
            if not dilihat:
                break
            sudah.update(k["id"] for k in dilihat)
            skor = nilai_ai(cfg, narasi, dilihat, batal, judul=judul, lihat=lihat, subjek=subjek,
                            alias=alias, spesifik=spesifik, latar=video, cerah=cerah)
            if skor:
                for k, s in zip(dilihat, skor):
                    if s is not None:
                        k["skor_ai"], k["isi_ai"] = s[0], s[1]
                        if s[2] is not None:
                            k["skor_latar"] = s[2]
                            k["setopik"] = setopik(k, kata_subjek)
                # cek nalar: yang dianggap tepat (≥7) diperiksa ulang lewat teks; yang tidak nyambung jadi "setema" (5)
                tinggi = [k for k in dilihat if (k.get("skor_ai") or 0) >= SKOR_BAGUS]
                nalar = cek_nalar(cfg, narasi, tinggi, batal, lihat=lihat, subjek=subjek) if tinggi else []
                for k, ok in zip(tinggi, nalar or []):
                    if not ok:
                        k["skor_ai"], k["nalar"] = 5, False
                log("  AI lihat: " + "; ".join(f"{'🎞️ ' if k['jenis'] == 'video' else ''}{k.get('isi_ai', '?')} "
                                               f"({k.get('skor_ai', '-')}"
                                               f"{', latar ' + str(k['skor_latar']) if k.get('skor_latar') is not None else ''}"
                                               f"{', tidak nyambung' if k.get('nalar') is False else ''})"
                                               for k in dilihat))
            # Lanjut melihat kandidat berikutnya sampai gambar bagus cukup untuk semua shot adegan ini.
            bisa = [k for k in kandidat if identitas(k) not in terpakai]
            if video:
                klip = sum(1 for k in bisa if k["jenis"] == "video" and nilai_latar(k) >= LATAR_BAGUS)
                stiker = sum(1 for k in bisa if k["jenis"] != "video" and (k.get("skor_ai") or 0) >= SKOR_BAGUS)
                sisa_klip = any(k["jenis"] == "video" and k["id"] not in sudah for k in bisa)
                if (klip >= butuh or not sisa_klip) and (stiker or not spesifik):
                    break
                if putaran >= 1 and klip >= max(1, (butuh + 1) // 2) and stiker:
                    break
                continue
            if sum(1 for k in bisa if k.get("skor_ai", 0) >= SKOR_BAGUS) >= butuh:
                break
            if putaran >= 1 and sum(1 for k in bisa if k.get("skor_ai", 0) >= SKOR_BAGUS - 1) >= butuh + 1 \
                    and not spesifik:
                break
        # Skor AI dominan; yang belum dinilai dianggap 4 (netral).
        kandidat.sort(key=lambda k: -(k.get("skor_ai", 4) * 1.0 + k["skor_h"] * 0.35))
    return kandidat


def _potong_analogi(semua, benda, batal, log, maks=4):
    """Benda utuh dipotong dari latarnya untuk ditumpuk menjadi gunungan. Foto yang bendanya close-up, menempel di
    tepi (gunung, lanskap), atau kecil di tengah pemandangan ditolak penyaring potongan → tidak masuk."""
    hasil, tolak = [], []
    for k in semua[:8]:
        if batal:
            batal.cek()
        try:
            b = siapkan(k, MAKS_FOTO, batal)
            if not b:
                continue
            png, alasan = potong.potong(b["file"])
        except Dibatalkan:
            raise
        except Exception as e:  # model belum bisa diunduh/dijalankan: pakai foto berbingkai seperti dulu
            log(f"  Pemotong latar tidak bisa dipakai ({e}) — foto “{benda}” ditumpuk berbingkai")
            return []
        if png:
            hasil.append({**k, "potongan": png})
            if len(hasil) >= maks:
                break
        else:
            tolak.append(alasan)
    if tolak:
        log(f"  Potongan “{benda}”: {len(hasil)} lolos, {len(tolak)} ditolak ({'; '.join(sorted(set(tolak))[:3])})")
    return hasil


def kandidat_analogi(cfg, benda, narasi, cek_gambar, batal=None, log=print):
    """Benda PEMBANDING dalam analogi narasi ("setara dengan menumpuk 1.600 gajah" → African elephant), untuk
    ditampilkan sebagai stiker bertumpuk. Hanya foto (bukan klip). Utamanya POTONGAN benda utuh tanpa latar (kunci
    "potongan") yang ditumpuk menjadi gunungan; kalau tidak ada yang bisa dipotong utuh (gunung, gedung), foto
    berbingkai yang menampilkan bendanya utuh. Dinilai AI kalau cek_gambar. Mengembalikan kandidat terbaik dulu,
    ditandai analogi=True."""
    tugas = [lambda: wikimedia(benda), lambda: openverse(benda)]
    if cfg.get("sumber_web") in ("semua", "berlisensi"):
        tugas.append(lambda: web_bing(benda, lisensi=cfg.get("sumber_web") == "berlisensi"))
    semua, lihat = [], set()
    for fn in tugas:
        try:
            for k in fn():
                if k["jenis"] == "gambar" and identitas(k) not in lihat and \
                        not BUKAN_SUBJEK.search(f"{k.get('judul') or ''} {k.get('teks') or ''}"):
                    lihat.add(identitas(k))
                    semua.append({**k, "kueri": benda, "analogi": True})
        except Exception as e:
            log(f"  Foto analogi “{benda}” gagal dicari: {e}")
    for k in semua:
        k["skor_h"] = nilai_heuristik(k, "16:9", set(), set(_kata(benda)))
    semua.sort(key=lambda k: -k["skor_h"])
    potongan = _potong_analogi(semua, benda, batal, log) if potong.tersedia() and semua else []
    if not cek_gambar or not semua:
        return (potongan or semua)[:3]
    ronde = []
    if potongan:
        # "sendirian": untuk "berat manusia dewasa" dulu lolos potongan anak perempuan memeluk anjing
        ronde.append((potongan, f"{benda} UTUH (seluruh badan/bentuknya terlihat dari ujung ke ujung, tidak "
                                "terpotong) yang sudah dipisahkan dari latarnya; satu benda/makhluk yang jelas, bukan "
                                "sebagian atau close-up, bukan kartun, bukan benda/hewan lain. Harus SENDIRIAN: kalau "
                                "ada orang, hewan, atau benda lain yang ikut menempel (orang memeluk hewan, orang di "
                                "atas kendaraan), skor subjek maksimal 3"))
    dipotong = {identitas(k) for k in potongan}
    ronde.append(([k for k in semua if identitas(k) not in dipotong][:4],
                  f"foto {benda} yang jelas: seluruh benda/makhluknya terlihat utuh (tidak terpotong tepi foto, bukan "
                  "close-up bagian), bukan kartun, bukan diagram, bukan kerumunan"))
    for calon, lihat in ronde:  # foto berbingkai hanya dinilai kalau tidak ada potongan yang pas
        skor = nilai_ai(cfg, narasi, calon[:4], batal, lihat=lihat, subjek=benda, spesifik=True)
        for k, s in zip(calon[:4], skor or []):
            if s:
                k["skor_ai"], k["isi_ai"] = s[0], s[1]
        tepat = sorted((k for k in calon[:4] if (k.get("skor_ai") or 0) >= SKOR_BAGUS), key=lambda k: -k["skor_ai"])
        if tepat:
            jenis = "potongan utuh" if tepat[0].get("potongan") else "foto berbingkai"
            log(f"  Analogi “{benda}”: {len(tepat)} {jenis} yang pas ({tepat[0].get('isi_ai')})")
            return tepat
    log(f"  Analogi “{benda}”: tidak ada foto yang pas")
    return []


# ---------------------------------------------------------------- unduh / potong

def _archive_file(ia_id):
    r = http_get(f"https://archive.org/metadata/{ia_id}")
    if not r.ok:
        return None, 0
    files = r.json().get("files", [])
    mp4 = [f for f in files if f.get("name", "").endswith(".mp4")]
    if not mp4:
        return None, 0
    f = max(mp4, key=lambda x: int(x.get("height") or 0) * 1000 + (1 if x.get("format") == "h.264" else 0))
    try:
        panjang = float(f.get("length") or 0)
    except ValueError:
        panjang = 0
    return f"https://archive.org/download/{ia_id}/{f['name']}", panjang


def detik_hitam(f, mulai=0.0, durasi=None):
    """Lama layar hitam pekat (fade ke hitam, jeda kosong di vlog) di potongan file video. Ambangnya ketat (hampir
    hitam murni di 99,5% layar ≥0,4 detik) supaya footage laut dalam yang memang gelap tidak ikut terhitung."""
    arg = [FFMPEG, "-hide_banner", "-nostats", "-ss", f"{mulai:.2f}", "-i", str(f)]
    if durasi:
        arg += ["-t", f"{durasi:.2f}"]
    try:
        r = subprocess.run(arg + ["-an", "-vf", "blackdetect=d=0.4:pic_th=0.995:pix_th=0.05", "-f", "null", "-"],
                           capture_output=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    return sum(float(d) for d in re.findall(r"black_duration:([\d.]+)", r.stderr.decode("utf-8", "replace")))


def siapkan(k, durasi, batal=None, bagian=0):
    """Bahan lokal untuk satu shot: {file, jenis, mulai}. None kalau gagal.
    Potongan yang memuat layar hitam (vlog Madeira yang fade ke hitam pernah jadi latar 1 detik hitam di video
    Komodo) diganti potongan lain dari klip yang sama, atau ditolak kalau semuanya hitam.
    bagian = potongan ke berapa dari video yang sama (tata visual "video + stiker" memakai satu klip panjang untuk
    beberapa shot, masing-masing bagian yang berbeda)."""
    kunci = hash_pendek(k["id"])
    if k["jenis"] == "gambar":
        tujuan = F_ASET / f"{kunci}.img"
        if k.get("referer"):
            f = unduh(k["url"], tujuan, batas_mb=40, batal=batal, headers={"Referer": k["referer"]})
        else:
            f = _unduh_wikimedia(k["url"], tujuan, k.get("lebar"), batas_mb=40, batal=batal)
        if not f:
            return None
        try:
            info = probe(f)
        except RuntimeError:
            return None
        if not info["video"] or info["lebar"] < 300:
            return None
        return {"file": str(f), "jenis": "gambar", "mulai": 0, "lebar": info["lebar"], "tinggi": info["tinggi"]}

    if not k.get("segmen"):
        f = unduh(k["url"], F_ASET / f"{kunci}.mp4", batas_mb=150, batal=batal)
        if not f:
            return None
        info = probe(f)
        if not info["video"]:
            return None
        sisa = max(0.0, info["durasi"] - durasi - 0.3)
        mulai = (int(kunci, 16) % 1000) / 1000 * min(sisa, 6)  # sedikit acak supaya tidak selalu detik 0
        if bagian:
            mulai = (mulai + bagian * (durasi + 0.6)) % (sisa + 0.01)
        for _ in range(4):
            if detik_hitam(f, mulai, durasi) < 0.4:
                break
            mulai = (mulai + durasi + 0.6) % (sisa + 0.01)
        else:
            return None
        return {"file": str(f), "jenis": "video", "mulai": round(mulai, 2), "lebar": info["lebar"],
                "tinggi": info["tinggi"], "durasi_file": info["durasi"]}

    perlu = round(durasi + 0.5, 2)
    tujuan = F_ASET / f"{kunci}-{int(perlu * 10)}{f'-b{bagian}' if bagian else ''}.mp4"
    if k["sumber"] == "Wikimedia" and not tujuan.exists():
        # Webm Wikimedia: ffmpeg yang melompat ke tengah file membuka banyak koneksi dan kena batas (429).
        # Cukup unduh bagian awal file dalam satu permintaan, lalu potong di laptop.
        total = k.get("durasi") or 0
        try:
            r = http_get(k["url"], headers={"Range": "bytes=0-0"})
            ukuran = int((r.headers.get("content-range") or "/0").rsplit("/", 1)[-1] or 0)
        except Exception:
            ukuran = 0
        laju = ukuran / total if ukuran and total else 1.5 * 1024 * 1024  # byte per detik
        mulai = min(25.0, total * 0.15) if total else 0.0  # lewati kartu judul di awal video sumber
        if bagian:
            mulai += bagian * (perlu + 0.5)
            if total:
                mulai = min(mulai, max(0.0, total - perlu - 0.2))
        sampai = int(min(60 * 1024 * 1024, (mulai + perlu + 4) * laju * 1.3 + 512 * 1024))
        awal = unduh(k["url"], F_ASET / f"{kunci}-awal.webm", batas_mb=61, batal=batal,
                     headers={"Range": f"bytes=0-{sampai}"})
        if not awal:
            return None
        try:
            ffmpeg(["-ss", f"{mulai:.2f}", "-i", str(awal), "-t", f"{perlu:.2f}", "-an",
                    "-vf", "scale=-2:'min(1080,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                    "-pix_fmt", "yuv420p", str(tujuan)], batal=batal, timeout=600)
        except RuntimeError:
            tujuan.unlink(missing_ok=True)
            return None
        finally:
            awal.unlink(missing_ok=True)

    # Video panjang (arsip): ambil potongan langsung dari internet, tidak perlu unduh seluruh film.
    url, panjang = (_archive_file(k["ia_id"]) if k.get("ia_id") else (k["url"], 0))
    if not url:
        return None
    if not tujuan.exists():
        if not panjang:
            try:
                panjang = probe(url, timeout=90)["durasi"]
            except RuntimeError:
                return None
        # Film arsip: lewati judul pembuka dan kredit penutup.
        awal = min(60.0, panjang * 0.15) if k["sumber"] == "Archive.org" else min(2.0, panjang * 0.05)
        akhir = max(awal, panjang - perlu - (30 if k["sumber"] == "Archive.org" else 1))
        posisi = ((int(kunci, 16) % 1000) / 1000 + bagian * 0.382) % 1  # tiap bagian lompat ±38% film
        mulai = awal + posisi * max(0.0, akhir - awal)
        try:
            ffmpeg(["-ss", f"{mulai:.2f}", "-user_agent", "Mozilla/5.0", "-i", url, "-t", f"{perlu:.2f}", "-an",
                    "-vf", "scale=-2:'min(1080,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                    "-pix_fmt", "yuv420p", str(tujuan)], batal=batal, timeout=600)
        except RuntimeError:
            tujuan.unlink(missing_ok=True)
            return None
    info = probe(tujuan)
    if not info["video"] or info["durasi"] < 0.5 or detik_hitam(tujuan) >= 0.4:
        tujuan.unlink(missing_ok=True)
        return None
    return {"file": str(tujuan), "jenis": "video", "mulai": 0, "lebar": info["lebar"], "tinggi": info["tinggi"],
            "durasi_file": info["durasi"]}


MAKS_FOTO = 3.0  # detik: foto layar penuh di tata visual "video + stiker" tidak boleh lebih lama dari ini
MIN_SHOT_VIDEO = 2.6  # detik: potongan klip yang lebih pendek terasa patah-patah


def jumlah_shot(durasi, format_video, video=False):
    """video=True: potongan cepat seperti video referensi pengguna (±260 potongan dalam 16 menit = ±3,7 detik)."""
    if video:
        maks = 3.5 if format_video == "9:16" else 4.2
    else:
        maks = 5.0 if format_video == "9:16" else 7.0
    n = max(1, math.ceil(durasi / maks - 0.15))
    if video:  # adegan 4,2 detik di Shorts dulu dibelah 2 x 2,1 detik: terasa patah-patah. Minimal ±2,6 detik.
        n = max(1, min(n, int(durasi / MIN_SHOT_VIDEO)))
    return n


def maks_bagian(k, durasi_shot):
    """Berapa shot boleh memakai klip yang sama (potongan berbeda) sebelum dianggap habis."""
    if k.get("sumber") == "Archive.org":
        return 6  # film arsip panjang, potongannya berjauhan
    total = k.get("durasi_file") or k.get("durasi") or 0
    if not total:
        return 2
    return max(1, min(4, int(total // (durasi_shot + 0.6))))
