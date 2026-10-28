"""Panggilan ke Ollama lokal (selalu streaming agar tidak kena timeout)."""
import json
import re
import time

import requests

from .alat import Dibatalkan

# Ollama yang mati sesaat (misalnya dimatikan sistem karena RAM penuh lalu dinyalakan ulang systemd) ditunggu dulu.
# Dulu tiga percobaan kata kunci terjadi di detik yang sama sehingga 11 dari 23 adegan jatuh ke kata kunci cadangan.
_TUNGGU = (10, 25, 45)


def chat(cfg, pesan, *, batal=None, **kw):
    for coba in range(len(_TUNGGU) + 1):
        try:
            return _chat(cfg, pesan, batal=batal, **kw)
        except _Putus as e:
            if coba == len(_TUNGGU):
                raise RuntimeError(str(e)) from None
            akhir = time.time() + _TUNGGU[coba]
            while time.time() < akhir:
                if batal and batal.aktif:
                    raise Dibatalkan()
                time.sleep(1)


class _Putus(Exception):
    """Ollama tidak bisa dihubungi atau jawabannya terputus (layak dicoba lagi)."""


# Prompt riset ±8.800 token di mini PC yang kepanasan (±3,5 token/detik) baru selesai dibaca ±42 menit,
# padahal selama itu Ollama belum mengirim apa pun; batas 1 jam membuat naskah Lubang hitam gagal.
def _chat(cfg, pesan, *, format=None, suhu=0.7, batal=None, saat_token=None, maks_token=None, timeout=7200):
    body = {
        "model": cfg["model"],
        "messages": pesan,
        "stream": True,
        "think": False,
        "options": {"temperature": suhu},
    }
    if format is not None:
        body["format"] = format
    if maks_token:
        body["options"]["num_predict"] = maks_token
    try:
        r = requests.post(cfg["ollama_url"].rstrip("/") + "/api/chat", json=body, stream=True, timeout=(10, timeout))
    except requests.ConnectionError:
        raise _Putus("Ollama tidak jalan. Buka aplikasi Ollama dulu, lalu coba lagi.")
    if r.status_code >= 500:
        raise _Putus(f"Ollama error {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
    teks = []
    try:
        with r:
            for baris in r.iter_lines():
                if batal and batal.aktif:
                    raise Dibatalkan()
                if not baris:
                    continue
                d = json.loads(baris)
                if d.get("error"):
                    galat = "Ollama: " + d["error"]
                    raise _Putus(galat) if "stopped" in d["error"] or "terminated" in d["error"] else RuntimeError(galat)
                potong = d.get("message", {}).get("content", "")
                if potong:
                    teks.append(potong)
                    if saat_token:
                        saat_token("".join(teks))
                if d.get("done"):
                    break
    except (requests.exceptions.ChunkedEncodingError, requests.ConnectionError) as e:
        raise _Putus(f"Jawaban Ollama terputus ({e})")  # "Response ended prematurely": runner mati di tengah jalan
    return "".join(teks)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
_TRAIL = re.compile(r",(\s*[}\]])")


def _calon_json(mentah):
    """Beberapa tebakan JSON dari jawaban model, dari yang paling apa adanya ke yang paling diperbaiki."""
    t = (mentah or "").strip()
    if not t:
        return
    yield t
    bersih = _FENCE.sub("", t).strip()
    if bersih != t:
        yield bersih
    # potong ke kurung terluar (objek {} atau larik []), lalu buang koma menggantung sebelum penutup
    for buka, tutup in (("{", "}"), ("[", "]")):
        a, b = bersih.find(buka), bersih.rfind(tutup)
        if 0 <= a < b:
            inti = bersih[a:b + 1]
            yield inti
            diperbaiki = _TRAIL.sub(r"\1", inti)
            if diperbaiki != inti:
                yield diperbaiki


def _urai_json(mentah):
    for calon in _calon_json(mentah):
        try:
            return json.loads(calon)
        except json.JSONDecodeError:
            continue
    return None


def chat_json(cfg, pesan, schema, **kw):
    # Walau keluaran dipandu skema, sesekali model mengirim JSON rusak (koma hilang, terpotong).
    # Coba urai + perbaiki; kalau tetap gagal, minta ulang ke model (jarang rusak dua kali).
    kw.setdefault("suhu", 0.3)
    for coba in range(3):
        hasil = _urai_json(chat(cfg, pesan, format=schema, **kw))
        if hasil is not None:
            return hasil
    raise RuntimeError("Jawaban AI bukan JSON yang valid")


def daftar_model(cfg):
    try:
        r = requests.get(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
