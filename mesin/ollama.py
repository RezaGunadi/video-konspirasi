"""Panggilan ke Ollama lokal (selalu streaming agar tidak kena timeout)."""
import json

import requests

from .alat import Dibatalkan


def chat(cfg, pesan, *, format=None, suhu=0.7, batal=None, saat_token=None, maks_token=None, timeout=3600):
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
        raise RuntimeError("Ollama tidak jalan. Buka aplikasi Ollama dulu, lalu coba lagi.")
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
    teks = []
    with r:
        for baris in r.iter_lines():
            if batal and batal.aktif:
                raise Dibatalkan()
            if not baris:
                continue
            d = json.loads(baris)
            if d.get("error"):
                raise RuntimeError("Ollama: " + d["error"])
            potong = d.get("message", {}).get("content", "")
            if potong:
                teks.append(potong)
                if saat_token:
                    saat_token("".join(teks))
            if d.get("done"):
                break
    return "".join(teks)


def chat_json(cfg, pesan, schema, **kw):
    kw.setdefault("suhu", 0.3)
    mentah = chat(cfg, pesan, format=schema, **kw)
    try:
        return json.loads(mentah)
    except json.JSONDecodeError:
        awal, akhir = mentah.find("{"), mentah.rfind("}")
        if awal >= 0 and akhir > awal:
            return json.loads(mentah[awal:akhir + 1])
        raise RuntimeError("Jawaban AI bukan JSON yang valid")


def daftar_model(cfg):
    try:
        r = requests.get(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
