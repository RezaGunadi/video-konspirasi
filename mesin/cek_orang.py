# -*- coding: utf-8 -*-
"""Scan proyek SELESAI: cari stiker/visual gambar-AI yang berisi WAJAH ORANG pada adegan yang
narasinya BUKAN soal manusia — bug lama di mana dreamshaper nyelipin potret orang ("night sky"
-> muka anak, "ocean exploration" -> cewek random). Jalan di TIAP mini PC lewat endpoint
/api/cek-orang (beban face-detect kebagi), hasil dikumpulkan laptop.

Face-detect: OpenCV Haar frontalface (CPU, tanpa GPU). Hanya cek gambar yang BENAR dipakai di shot
(pilih/stiker) dan bersumber 'AI'. Jalan di thread latar; /api/cek-orang?mulai=1 memulai,
/api/cek-orang mengembalikan progres + hasil."""
import os
import threading
import time

from . import proyek
from .footage import _NARASI_ORANG

_state = {"status": "idle", "mulai": 0, "selesai": 0, "total": 0, "dicek": 0, "hasil": [], "galat": ""}
_slock = threading.Lock()
_CASC = None


def _casc():
    global _CASC
    if _CASC is None:
        import cv2
        _CASC = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _CASC


def _wajah(fp):
    """Jumlah wajah frontal di gambar fp (0 kalau gagal baca)."""
    import cv2
    im = cv2.imread(fp)
    if im is None:
        return 0
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    f = _casc().detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(50, 50))
    return len(f)


def _scan():
    try:
        with proyek._lock:
            ps = [p for p in proyek._proyek.values() if p.get("status") == "selesai"]
        with _slock:
            _state.update({"total": len(ps), "selesai": 0, "dicek": 0, "hasil": []})
        for p in ps:
            try:
                judul = (p.get("meta") or {}).get("judul") or p.get("nama") or ""
                bad = []
                for i, a in enumerate(p.get("adegan") or []):
                    narasi = a.get("teks") or ""
                    if _NARASI_ORANG.search(f"{narasi} {judul}"):
                        continue  # adegan/topik memang soal manusia: orang wajar
                    kand = a.get("kandidat") or []
                    idxs = set()
                    for s in a.get("shots") or []:
                        for key in ("pilih", "stiker"):
                            if s.get(key) is not None:
                                idxs.add(s[key])
                    for idx in idxs:
                        if not (0 <= idx < len(kand)):
                            continue
                        k = kand[idx]
                        if k.get("jenis") != "gambar" or not str(k.get("sumber") or "").startswith("AI"):
                            continue
                        fp = k.get("file_lokal")
                        if not fp or not os.path.exists(fp):
                            continue
                        with _slock:
                            _state["dicek"] += 1
                        if _wajah(fp) > 0:
                            bad.append({"adegan": i, "teks": narasi[:90],
                                        "kand": (k.get("judul") or k.get("teks") or "")[:50]})
                if bad:
                    with _slock:
                        _state["hasil"].append({"id": p["id"], "judul": judul,
                                                "diunduh": bool(p.get("diunduh")), "jumlah": len(bad),
                                                "adegan": bad})
            except Exception:
                pass
            with _slock:
                _state["selesai"] += 1
        with _slock:
            _state["status"] = "selesai"
    except Exception as e:
        with _slock:
            _state["status"] = "galat"
            _state["galat"] = repr(e)[:200]


def mulai():
    with _slock:
        if _state["status"] == "jalan":
            return dict(_state)
        _state.update({"status": "jalan", "mulai": time.time(), "galat": ""})
    threading.Thread(target=_scan, daemon=True).start()
    return status()


def status():
    with _slock:
        return dict(_state)
