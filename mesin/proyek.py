"""Proyek video + antrian kerja.

Langkah: riset → naskah → adegan → suara → footage → render. Tiap langkah hanya mengerjakan bagian yang belum ada,
jadi proyek bisa dilanjutkan setelah server mati, dan edit naskah / ganti footage cukup mengulang langkah setelahnya.
"""
import datetime as dt
import difflib
import json
import math
import os
import random
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

from . import (config, efek, footage, hidup, maskot, naskah, recreate, render, riset, suara, suara_mirip,
               suara_saya)
from .alat import (INPUT, OUTPUT, PROYEK, Batal, Dibatalkan, baca_json, ffmpeg, hash_pendek, probe, slug,
                   tulis_json)

LANGKAH = ["riset", "naskah", "adegan", "suara", "footage", "render"]
BOBOT = {"riset": 5, "naskah": 20, "adegan": 10, "suara": 10, "footage": 35, "render": 20}
OPSI_KUNCI = ["mode", "format", "durasi", "suara", "kecepatan", "nada", "subtitle", "musik", "volume_musik",
              "cek_gambar", "cek_naskah", "riset", "gaya", "isi_layar", "disclaimer", "teks_disclaimer", "gaya_naskah", "cta",
              "jumlah_reels", "durasi_reels", "cta_reels", "suara_alami", "animasi", "visual", "maskot"]

_lock = threading.RLock()
_proyek = {}       # id → dict (sumber kebenaran; disimpan ke disk berkala)
_batal = {}        # id → Batal
_tertunda = {}     # id → [(fungsi, antri)] perubahan GUI yang menunggu prosesnya berhenti
_simpan_terakhir = {}
_bangun = threading.Event()


# ---------------------------------------------------------------- penyimpanan

def _path(pid):
    return PROYEK / pid / "proyek.json"


def _simpan(p, paksa=False):
    now = time.time()
    if not paksa and now - _simpan_terakhir.get(p["id"], 0) < 1.5:
        return
    _simpan_terakhir[p["id"]] = now
    with _lock:
        tulis_json(_path(p["id"]), p)


def muat_semua():
    for d in PROYEK.iterdir():
        p = baca_json(d / "proyek.json")
        if p and p.get("id"):
            if p.get("status") == "jalan":
                p["status"] = "antri"  # server mati di tengah jalan: lanjutkan
                p["antri_sejak"] = "0"  # yang tadi sedang jalan dikerjakan duluan
            if "visual" not in (p.get("opsi") or {}):
                p.setdefault("opsi", {})["visual"] = "klasik"  # proyek sebelum ada "video + stiker": tetap seperti dulu
            p.setdefault("opsi", {}).setdefault("maskot", False)  # proyek sebelum ada maskot: render ulang tetap sama
            p["opsi"] = _opsi_bersih(p.get("opsi") or {})  # proyek lama: lengkapi opsi baru
            if "suara" in p.get("selesai", []) and not p.get("narasi_mp3"):
                # Proyek dengan suara per adegan (versi lama): dibacakan ulang sekali jalan saat diproses lagi.
                p["selesai"] = [x for x in p["selesai"] if x not in ("suara", "footage", "render")]
            _proyek[p["id"]] = p


def _sekarang():
    return dt.datetime.now().isoformat(timespec="seconds")


def log(p, teks):
    jam = dt.datetime.now().strftime("%H:%M:%S")
    with _lock:
        p.setdefault("log", []).append(f"{jam}  {teks}")
        p["log"] = p["log"][-400:]
        p["pesan"] = teks
    _simpan(p)


def _opsi_bersih(opsi):
    bawaan = config.muat()["default"]
    hasil = {k: opsi.get(k, bawaan[k]) for k in OPSI_KUNCI}
    hasil["format"] = hasil["format"] if hasil["format"] in ("16:9", "keduanya") else "9:16"
    hasil["mode"] = hasil["mode"] if hasil["mode"] in ("bacakan", "ringkas", "teaser", "recreate") else "tulis"
    hasil["kembar"] = bool(opsi.get("kembar"))  # proyek 16:9 yang nanti membuat reels 9:16-nya
    hasil["jumlah_reels"] = max(1, min(5, int(hasil["jumlah_reels"])))
    hasil["durasi_reels"] = max(20, min(90, int(hasil["durasi_reels"])))
    hasil["cta_reels"] = " ".join(str(hasil.get("cta_reels") or "").split())[:220]
    hasil["durasi"] = max(20, min(1200, int(hasil["durasi"])))
    hasil["kecepatan"] = max(-30, min(30, int(hasil["kecepatan"])))
    hasil["nada"] = max(-20, min(20, int(hasil["nada"])))
    hasil["volume_musik"] = max(0, min(50, int(hasil["volume_musik"])))
    if hasil["suara"] not in suara.SUARA and hasil["suara"] != suara_saya.KODE:
        hasil["suara"] = "id-ID-ArdiNeural"
    hasil["cta"] = " ".join(str(hasil.get("cta") or "").split())[:220]
    hasil["suara_alami"] = bool(hasil["suara_alami"])
    hasil["animasi"] = hasil["animasi"] if hasil["animasi"] in ("hidup", "zoom") else "hidup"
    hasil["visual"] = hasil["visual"] if hasil["visual"] in ("video_stiker", "klasik") else "video_stiker"
    hasil["gaya"] = hasil["gaya"] if hasil["gaya"] in ("misterius", "cerah", "natural") else "misterius"
    hasil["maskot"] = bool(hasil["maskot"])
    if hasil["gaya_naskah"] not in ("sains", "meyakinkan", "twist", "seimbang", "bangun_teori", "edukasi"):
        hasil["gaya_naskah"] = "meyakinkan"
    if hasil["disclaimer"] not in ("awal", "akhir", "keduanya", "tidak"):
        hasil["disclaimer"] = "awal"
    hasil["teks_disclaimer"] = " ".join(str(hasil["teks_disclaimer"] or "").split())[:400] or config.DISCLAIMER_BAWAAN
    return hasil


def buat(teks, opsi, nama=None, ekstra=None):
    teks = (teks or "").strip()
    if not teks:
        raise ValueError("Teks kosong")
    opsi = _opsi_bersih(opsi)
    if opsi["format"] == "keduanya":  # YouTube 16:9 dulu; versi Shorts 9:16 dibuat setelah naskahnya final
        opsi.update(format="16:9", kembar=True)
    pid = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + f"{random.randint(0, 0xffff):04x}"
    (PROYEK / pid).mkdir(parents=True, exist_ok=True)
    p = {"id": pid, "dibuat": dt.datetime.now().isoformat(timespec="seconds"),
         "nama": (nama or teks.splitlines()[0])[:80], "sumber_teks": teks, "opsi": opsi,
         "status": "antri", "antri_sejak": _sekarang(), "langkah": "", "selesai": [], "progres": 0,
         "pesan": "Menunggu giliran", "log": [],
         "riset": [], "naskah": "", "meta": {}, "adegan": [], "hasil": {}, "galat": ""}
    p.update(ekstra or {})
    with _lock:
        _proyek[pid] = p
    _simpan(p, paksa=True)
    _bangun.set()
    return p


def daftar():
    with _lock:
        semua = sorted(_proyek.values(), key=lambda p: p["dibuat"], reverse=True)
        return [{k: p.get(k) for k in ("id", "dibuat", "nama", "status", "langkah", "progres", "pesan", "galat",
                                        "hasil", "opsi", "perubahan")} | {"judul": p.get("meta", {}).get("judul", "")}
                for p in semua]


def detail(pid):
    with _lock:
        p = _proyek.get(pid)
        if not p:
            return None
        hasil = {k: v for k, v in p.items() if k not in ("adegan", "gambar_topik", "transkrip")}
        hasil["reels"] = [{"id": i, "nama": _proyek[i]["nama"], "status": _proyek[i]["status"],
                           "sudut": _proyek[i].get("sudut", "")} for i in _anak_reels(p)]
        hasil["link_induk"] = _link_induk(p)
        hasil["adegan"] = []
        for a in p.get("adegan", []):
            kand = a.get("kandidat") or []
            dipakai = {s.get("pilih") for s in a.get("shots", [])} | {s.get("stiker") for s in a.get("shots", [])}
            hasil["adegan"].append({
                "teks": a["teks"], "q": a.get("q"), "durasi": a.get("durasi"), "mulai": a.get("mulai"),
                "shots": [{"pilih": s.get("pilih"), "frames": s.get("frames"),
                           "siap": bool(s.get("bahan")) or bool(s.get("banding")),
                           "kandidat": _ringkas(kand[s["pilih"]]) if s.get("pilih") is not None and s["pilih"] < len(kand) else None,
                           "stiker": _ringkas(kand[s["stiker"]]) if s.get("stiker") is not None and s["stiker"] < len(kand) else None,
                           "banding": {x: dict(_ringkas(a["banding"][x].get("k") or {}), label=a["banding"][x]["label"])
                                       for x in ("kiri", "kanan")} if s.get("banding") and a.get("banding") else None}
                          for s in a.get("shots", [])],
                "alternatif": [dict(_ringkas(k), index=i) for i, k in enumerate(kand[:12]) if i not in dipakai],
            })
        return hasil


def _ringkas(k):
    return {x: k.get(x) for x in ("id", "sumber", "jenis", "thumb", "halaman", "lisensi", "pembuat", "skor_ai",
                                  "isi_ai", "judul")}


# ---------------------------------------------------------------- perubahan dari GUI

def _terapkan(p, fungsi, antri, tadinya_jalan):
    """Terapkan perubahan dari GUI (dipanggil dengan _lock)."""
    fungsi(p)
    p["galat"] = ""
    if antri or tadinya_jalan:
        p["perubahan"] = False
        if p["status"] != "cek_naskah" or "naskah" in p["selesai"]:
            p["status"] = "antri"
            p["antri_sejak"] = _sekarang()
            p["pesan"] = "Menunggu giliran"
    else:
        p["perubahan"] = True


def _hentikan_lalu(pid, fungsi, antri=True):
    """Kalau proyek sedang dikerjakan, hentikan dulu; lalu terapkan perubahan dan antrikan lagi.

    antri=False (ganti footage): proyek yang sudah selesai tidak langsung dirender ulang, supaya beberapa shot bisa
    diganti dulu lalu dirender sekali lewat tombol "Render ulang".
    Langkah yang tidak bisa disela (Whisper atas narasi 5 menit, satu panggilan ffmpeg) bisa jalan beberapa menit
    lagi. Perubahan TIDAK diterapkan selagi proses masih jalan (dulu begitu: data proyek ditimpa di tengah langkah,
    lalu proses berakhir "dibatalkan" dan permintaan tulis ulang hilang) — disimpan di _tertunda dan diterapkan
    oleh kerjakan() begitu berhenti.
    """
    with _lock:
        p = _proyek.get(pid)
        if not p:
            raise KeyError(pid)
        tadinya_jalan = p["status"] in ("jalan", "antri")
        if p["status"] == "jalan" and pid in _batal:
            _batal[pid].set()
    for _ in range(50):
        with _lock:
            if p["status"] != "jalan":
                break
        time.sleep(0.1)
    with _lock:
        if p["status"] == "jalan":
            _tertunda.setdefault(pid, []).append((fungsi, antri))
            p["pesan"] = "Menghentikan proses… perubahan diterapkan begitu langkah ini berhenti"
            return p
        _terapkan(p, fungsi, antri, tadinya_jalan)
    _simpan(p, paksa=True)
    _bangun.set()
    return p


def _buang_langkah(p, *langkah):
    p["selesai"] = [x for x in p["selesai"] if x not in langkah]


def edit_naskah(pid, teks_baru):
    def f(p):
        p["naskah"] = naskah.bersihkan(teks_baru)
        p["adegan"] = []
        _buang_langkah(p, "adegan", "suara", "footage", "render")
        if "naskah" not in p["selesai"]:
            p["selesai"].append("naskah")
        log(p, "Naskah diedit — adegan, suara, footage, dan video dibuat ulang")
    return _hentikan_lalu(pid, f)


def lanjut(pid):
    def f(p):
        if "naskah" not in p["selesai"] and p.get("naskah"):
            p["selesai"].append("naskah")
        p["status"] = "antri"
    return _hentikan_lalu(pid, f)


def ulangi(pid, opsi_baru=None):
    """Coba lagi setelah gagal/batal; opsi tampilan/suara bisa diganti."""
    def f(p):
        if opsi_baru:
            lama = p["opsi"]
            baru = _opsi_bersih({**lama, **opsi_baru, "format": lama["format"], "mode": lama["mode"]})
            if any(baru[k] != lama.get(k, baru[k]) for k in ("suara", "kecepatan", "nada", "suara_alami")):
                for a in p["adegan"]:
                    a.pop("shots", None)
                p.pop("narasi_mp3", None)
                _buang_langkah(p, "suara", "footage")
            if any(baru[k] != lama.get(k) for k in ("disclaimer", "teks_disclaimer")):
                _buang_langkah(p, "suara")
            if (baru["cek_gambar"] and not lama["cek_gambar"]) or baru["visual"] != lama.get("visual"):
                # tata visual lain = kandidat lain (video + stiker juga mencari klip untuk kata kunci suasana)
                for a in p["adegan"]:
                    for kunci in ("kandidat", "shots", "latar_dicari"):
                        a.pop(kunci, None)
                _buang_langkah(p, "footage")
            p["opsi"] = baru
        if any(not s.get("bahan") for a in p["adegan"] for s in a.get("shots", [])):
            _buang_langkah(p, "footage")  # shot yang tadinya latar gelap dicarikan footage lagi
        _buang_langkah(p, "render")
        log(p, "Dibuat ulang dengan pengaturan terbaru")
    return _hentikan_lalu(pid, f)


def pilih_footage(pid, ia, js, index=None, file_lokal=None):
    """Ganti footage satu shot: index kandidat tertentu, berikutnya (None), atau file upload sendiri."""
    def f(p):
        a = p["adegan"][ia]
        s = a["shots"][js]
        kand = a.setdefault("kandidat", [])
        if file_lokal:
            info = probe(file_lokal)
            jenis = "gambar" if info["durasi"] < 0.5 or Path(file_lokal).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else "video"
            kand.insert(0, {"id": f"lokal-{Path(file_lokal).name}", "sumber": "Upload sendiri", "jenis": jenis,
                            "file": str(file_lokal), "lebar": info["lebar"], "tinggi": info["tinggi"],
                            "lisensi": "milik sendiri", "pembuat": "", "thumb": None})
            for s2 in a["shots"]:  # index bergeser karena sisip di depan
                for kunci in ("pilih", "stiker"):
                    if s2.get(kunci) is not None:
                        s2[kunci] += 1
            s["pilih"] = 0
        elif index is not None:
            s["pilih"] = int(index)
        else:
            dipakai = _dipakai(p)
            mulai = (s.get("pilih") or 0) + 1
            urutan = list(range(mulai, len(kand))) + list(range(0, mulai))
            s["pilih"] = next((i for i in urutan if footage.identitas(kand[i]) not in dipakai),
                              urutan[0] if urutan else None)
        if s.get("pilih") is not None and kand[s["pilih"]]["jenis"] == "video":
            s["bagian"] = _bagian_bebas(p, kand[s["pilih"]], kecuali=s)  # potongan yang belum tampil di shot lain
        s["bahan"] = None
        s.pop("gagal", None)
        _buang_langkah(p, "footage", "render")
        log(p, f"Footage adegan {ia + 1} shot {js + 1} diganti")
    return _hentikan_lalu(pid, f, antri=False)


def hapus_stiker(pid, ia, js):
    """Buang stiker foto dari satu shot (footage latarnya tetap); berlaku setelah Render ulang."""
    def f(p):
        s = p["adegan"][ia]["shots"][js]
        s["stiker"] = None
        s.pop("stiker_bahan", None)
        _buang_langkah(p, "render")
        log(p, f"Stiker adegan {ia + 1} shot {js + 1} dihapus")
    return _hentikan_lalu(pid, f, antri=False)


def tulis_ulang(pid, opsi_baru=None, teks=None, sudut=None):
    """Buat ulang dari awal: riset (termasuk topik terkait), naskah, judul, adegan, suara, footage, render.
    opsi_baru boleh mengganti gaya cerita, durasi, CTA, dan pengaturan reels. Untuk reels teaser: naskahnya ditulis
    ulang dari naskah video panjang yang sama, dengan fokus (sudut) baru kalau diisi."""
    def f(p):
        lama = p["opsi"]
        if p["opsi"]["mode"] == "recreate":
            if sudut and sudut.strip():
                p["recreate"]["tema"] = " ".join(sudut.split())[:300]
            p["selesai"], p["naskah"], p["bab"] = ["riset"], "", []
        elif p["opsi"]["mode"] == "teaser":
            if opsi_baru:
                ganti = {k: opsi_baru[k] for k in ("gaya_naskah",) if k in opsi_baru}
                if "durasi_reels" in opsi_baru:
                    ganti["durasi"] = opsi_baru["durasi_reels"]
                if "cta_reels" in opsi_baru:
                    ganti["cta"] = opsi_baru["cta_reels"]
                p["opsi"] = _opsi_bersih({**lama, **ganti})
            if sudut and sudut.strip():
                p["sudut"] = " ".join(sudut.split())[:300]
            p["selesai"], p["naskah"], p["bab"] = ["riset"], "", []
        else:
            if opsi_baru:
                boleh = ("gaya_naskah", "durasi", "cta", "jumlah_reels", "durasi_reels", "cta_reels")
                p["opsi"] = _opsi_bersih({**lama, **{k: v for k, v in opsi_baru.items() if k in boleh},
                                          "format": lama["format"], "mode": lama["mode"]})
            if teks and teks.strip():  # topik/arahan cerita baru dari pengguna
                p["sumber_teks"] = teks.strip()
            if p["opsi"]["mode"] == "bacakan":  # naskah dari pengguna: jangan ditulis ulang AI
                _buang_langkah(p, "adegan", "suara", "footage", "render")
            else:
                p["selesai"] = []
                p["riset"], p["naskah"], p["bab"] = [], "", []
        p["adegan"] = []
        for kunci in ("gambar_topik", "narasi_mp3", "meta"):
            p.pop(kunci, None)
        p["meta"] = {}
        if p["opsi"].get("kembar"):
            p["kembar_segarkan"] = True  # reels ikut dibuat ulang setelah naskah baru jadi
        log(p, f"Tulis ulang naskah{' reels' if p['opsi']['mode'] == 'teaser' else ''} "
               f"(gaya {p['opsi']['gaya_naskah']}, ±{p['opsi']['durasi']} detik)")
    return _hentikan_lalu(pid, f)


def cari_ulang_footage(pid):
    """Untuk video yang sudah jadi: kata kunci, kandidat, dan pilihan footage dibuat ulang dari nol
    (dengan gambar topik + AI melihat gambar), naskah dan suara tetap."""
    def f(p):
        for a in p["adegan"]:
            for kunci in ("q", "kandidat", "shots", "latar_dicari"):
                a.pop(kunci, None)
            for sisi in ("kiri", "kanan"):
                (a.get("banding") or {}).get(sisi, {}).pop("k", None)
                (a.get("banding") or {}).get(sisi, {}).pop("bahan", None)
            (a.get("banding") or {}).pop("siap", None)
        p.pop("gambar_topik", None)
        p["opsi"]["cek_gambar"] = True
        _buang_langkah(p, "footage", "render")
        log(p, "Cari ulang semua footage (gambar topik + AI memilih)")
    return _hentikan_lalu(pid, f)


def batalkan(pid):
    with _lock:
        p = _proyek.get(pid)
        if not p:
            return
        if pid in _batal:
            _batal[pid].set()
        if p["status"] in ("antri", "cek_naskah"):
            p["status"] = "dibatalkan"
            p["pesan"] = "Dibatalkan"
    _simpan(p, paksa=True)


def hapus(pid):
    batalkan(pid)
    for _ in range(100):
        with _lock:
            if _proyek.get(pid, {}).get("status") != "jalan":
                break
        time.sleep(0.1)
    with _lock:
        _proyek.pop(pid, None)
    shutil.rmtree(PROYEK / pid, ignore_errors=True)


# ---------------------------------------------------------------- langkah-langkah

def _foto_banding(a):
    bd = a.get("banding") or {}
    return [bd[x]["k"] for x in ("kiri", "kanan") if (bd.get(x) or {}).get("k")]


def _dipakai(p):
    """Identitas gambar yang sudah dipakai shot mana pun (lihat footage.identitas), termasuk foto perbandingan dan
    stiker."""
    ids = set()
    for a in p["adegan"]:
        kand = a.get("kandidat") or []
        for s in a.get("shots", []):
            for kunci in ("pilih", "stiker"):
                if s.get(kunci) is not None and s[kunci] < len(kand):
                    ids.add(footage.identitas(kand[s[kunci]]))
        ids.update(footage.identitas(k) for k in _foto_banding(a))
    return ids


def _pakai_klip(p, kecuali=()):
    """identitas klip → potongan (bagian) yang sudah tampil. kecuali = shot yang sedang direncanakan ulang."""
    hasil = {}
    for a in p["adegan"]:
        kand = a.get("kandidat") or []
        for s in a.get("shots", []):
            if any(s is x for x in kecuali) or s.get("pilih") is None or s["pilih"] >= len(kand):
                continue
            if kand[s["pilih"]]["jenis"] == "video":
                hasil.setdefault(footage.identitas(kand[s["pilih"]]), set()).add(s.get("bagian") or 0)
    return hasil


def _bagian_bebas(p, k, kecuali=None, pakai=None):
    """Potongan terkecil dari klip k yang belum tampil di shot lain."""
    pakai = _pakai_klip(p, [kecuali] if kecuali else []) if pakai is None else pakai
    terpakai = pakai.get(footage.identitas(k), set())
    return next(n for n in range(len(terpakai) + 1) if n not in terpakai)


def _progres(p, langkah, bagian=0.0):
    selesai = sum(BOBOT[x] for x in p["selesai"] if x in BOBOT)
    p["progres"] = min(99, int(selesai + BOBOT.get(langkah, 0) * bagian))


def l_riset(p, cfg, batal):
    if p["opsi"]["mode"] == "recreate":
        return _siapkan_recreate(p, cfg, batal)
    if p["opsi"]["mode"] != "tulis" or not p["opsi"]["riset"]:
        return
    p["riset"] = riset.kumpulkan(cfg, p["sumber_teks"], batal, log=lambda t: log(p, t),
                                 panjang=p["opsi"]["durasi"] > 180, gali=p["opsi"]["gaya_naskah"] == "bangun_teori")
    if not p["riset"]:
        log(p, "Tidak ada artikel Wikipedia yang cocok — naskah ditulis dari pengetahuan umum model")


def l_naskah(p, cfg, batal):
    if p["opsi"]["mode"] == "bacakan":
        p["naskah"] = naskah.bersihkan(p["sumber_teks"])
        log(p, f"Naskah dari teks: {len(p['naskah'].split())} kata")
        return
    ringkas = p["opsi"]["mode"] == "ringkas"
    teaser = p["opsi"]["mode"] == "teaser"
    target = naskah.target_kata(60 if ringkas else p["opsi"]["durasi"])
    jenis = "Shorts dari video panjang " if ringkas else "reels teaser " if teaser else ""
    log(p, f"AI menulis naskah {jenis}±{target} kata (model lokal, sabar ya)…")
    if teaser:
        log(p, f"Fokus reels ini: {p.get('sudut') or '-'}")

    def saat_token(teks, sudah=0, total=target, label=""):
        n = sudah + len(teks.split())
        p["pesan"] = f"Menulis naskah{' ' + label if label else ''}… {n}/{total} kata"
        _progres(p, "naskah", min(0.95, n / max(1, total)))

    if p["opsi"]["mode"] == "recreate":
        rc = p["recreate"]
        log(p, f"Tema short ini: {rc['tema']} (gaya {'teaser' if rc['gaya_short'] == 'teaser' else 'mandiri'})")
        p["naskah"], p["bab"] = naskah.short_dari_sumber(
            cfg, recreate.teks_transkrip(p.get("transkrip") or []), rc["tema"], p["opsi"]["durasi"],
            rc["gaya_short"], batal, saat_token, cta=p["opsi"]["cta"]), []
    elif teaser:
        p["naskah"], p["bab"] = naskah.teaser(cfg, p["sumber_teks"], p.get("sudut") or "bagian paling mengejutkan",
                                              p["opsi"]["durasi"], batal, saat_token, cta=p["opsi"]["cta"],
                                              gaya=p["opsi"]["gaya_naskah"]), []
    elif ringkas:
        p["naskah"], p["bab"] = naskah.ringkas_shorts(cfg, p["sumber_teks"], batal, saat_token,
                                                      gaya=p["opsi"]["gaya_naskah"], cta=p["opsi"]["cta"]), []
    else:
        p["naskah"], p["bab"] = naskah.tulis(cfg, p["sumber_teks"], p["riset"], p["opsi"]["durasi"], batal,
                                             saat_token, log=lambda t: log(p, t), gaya=p["opsi"]["gaya_naskah"],
                                             cta=p["opsi"]["cta"])
    if len(p["naskah"].split()) < 20:
        raise RuntimeError("Naskah dari AI terlalu pendek, coba lagi")
    log(p, f"Naskah jadi: {len(p['naskah'].split())} kata")


def l_adegan(p, cfg, batal):
    log(p, "Membuat judul, deskripsi, dan tag…")
    p["meta"] = naskah.meta(cfg, p["naskah"], p["opsi"]["format"], batal, log=lambda t: log(p, t),
                            gaya=p["opsi"]["gaya_naskah"])
    log(p, f"Judul: {p['meta']['judul']}")
    teks_adegan = naskah.pecah_adegan(p["naskah"], p["opsi"]["format"])
    log(p, f"{len(teks_adegan)} adegan — AI memilih kata kunci footage…")
    q = naskah.kata_kunci_adegan(cfg, p["meta"]["judul"], teks_adegan, batal, log=lambda t: log(p, t),
                                 subjek=_subjek(p), artikel=_artikel_bukti(p), fakta=_fakta(p))
    _lengkapi_artikel(p, teks_adegan, q)
    p["adegan"] = [{"teks": t, "q": qq} for t, qq in zip(teks_adegan, q)]
    # 🆚 dua foto "MIRIP?": bumbu video misteri/teori, tidak untuk video sains/fakta
    if p["opsi"].get("gaya_naskah", "twist") not in ("seimbang", "sains") and p["opsi"]["mode"] != "recreate":
        bd = naskah.cari_perbandingan(cfg, p["meta"]["judul"], teks_adegan, batal, log=lambda t: log(p, t),
                                      sumber=[s["judul"] for s in p.get("riset") or []])
        if bd:
            p["adegan"][bd["no"] - 1]["banding"] = {"kiri": bd["kiri"], "kanan": bd["kanan"],
                                                    "mode": bd.get("mode", "dua_foto")}


def _token(teks):
    return re.findall(r"[\w'-]+", teks.lower())


def _petakan_kata(adegan, kata):
    """Indeks kata TTS pertama & terakhir untuk tiap adegan (naskah dibacakan sekali jalan)."""
    pemilik = [i for i, a in enumerate(adegan) for _ in _token(a["teks"])]
    naskah_tok = [t for a in adegan for t in _token(a["teks"])]
    ucap_tok, ucap_idx = [], []
    for j, k in enumerate(kata):
        for t in _token(k["teks"]):
            ucap_tok.append(t)
            ucap_idx.append(j)
    peta = {}
    for blok in difflib.SequenceMatcher(a=naskah_tok, b=ucap_tok, autojunk=False).get_matching_blocks():
        for d in range(blok.size):
            peta[blok.a + d] = ucap_idx[blok.b + d]
    rentang = [[None, None] for _ in adegan]
    for posisi, i in enumerate(pemilik):
        if posisi in peta:
            j = peta[posisi]
            rentang[i][0] = j if rentang[i][0] is None else min(rentang[i][0], j)
            rentang[i][1] = j if rentang[i][1] is None else max(rentang[i][1], j)
    # Adegan yang tidak ketemu (jarang): pinjam posisi tetangga
    for i, r in enumerate(rentang):
        if r[0] is None:
            sebelum = next((rentang[x][1] for x in range(i - 1, -1, -1) if rentang[x][1] is not None), -1)
            r[0] = r[1] = min(len(kata) - 1, sebelum + 1)
    return rentang


def l_suara(p, cfg, batal):
    """Seluruh naskah dibacakan SEKALI JALAN supaya intonasi dan jeda antarkalimat alami (dulu tiap adegan
    dibacakan terpisah: intonasi mulai dari nol dan ada jeda ±1,2 detik di tiap sambungan). Adegan lalu
    dipotong mengikuti waktu kata: titik potong di tengah jeda antara kata terakhir adegan dan kata pertama
    adegan berikutnya."""
    o = p["opsi"]
    FPS = render.FPS
    saya = o["suara"] == suara_saya.KODE
    if saya and not suara_saya.ada():
        raise RuntimeError("Profil “Suara saya” belum dibuat (data/suara-saya) atau OpenVoice belum terpasang")
    # Suara saya: Edge dasar (nadanya digeser ke nada bicara pengguna), warna suaranya diubah setelah Whisper
    nama_suara, nada = (suara_saya.suara_dasar(), suara_saya.nada_dasar()) if saya else (o["suara"], o["nada"])
    log(p, "Membacakan naskah (sekali jalan)…")
    s = suara.bacakan(p["naskah"], nama_suara, o["kecepatan"], nada, batal)
    kata = s["kata"]
    if not kata:
        raise RuntimeError("Edge TTS tidak mengirim waktu kata; coba lagi")
    p["pesan"] = "Mencocokkan waktu subtitle dengan suara (Whisper)…"
    kata, p["waktu_whisper"] = suara.selaraskan(s["mp3"], kata, log=lambda t: log(p, t), batal=batal)
    narasi = s["mp3"]
    if saya:
        # diubah SEBELUM efek rekaman: OpenVoice lebih akurat pada suara TTS yang masih bersih
        p["pesan"] = "Mengubah warna suara jadi suaramu (OpenVoice)…"
        narasi = suara_saya.ubah(narasi)
        log(p, f"Narasi memakai suaramu (klon dari {suara_saya.profil().get('jumlah_ref', 0)} potongan rekaman)")
    if o.get("suara_alami", True):
        # jeda antarkalimat seperti narator manusia (Ardi menjeda seragam ±1,1 detik) + warna rekaman
        narasi, kata = suara.manusiawikan(narasi, kata, p["naskah"], batal)
        s = {**s, "durasi": probe(narasi)["durasi"]}
        log(p, "Suara dibuat lebih alami: jeda antarkalimat bervariasi + warna rekaman")
    rentang = _petakan_kata(p["adegan"], kata)
    akhir_utama = max(s["durasi"], kata[-1]["t1"] + 0.5) + 0.4
    potong = [0]
    for i in range(1, len(p["adegan"])):
        selesai_lalu = kata[rentang[i - 1][1]]["t1"]
        mulai_ini = kata[rentang[i][0]]["t0"]
        t = (selesai_lalu + mulai_ini) / 2 if mulai_ini > selesai_lalu else mulai_ini - 0.05
        potong.append(max(potong[-1] + 15, round(t * FPS)))  # minimal 0,5 detik per adegan
    potong.append(max(potong[-1] + 15, round(akhir_utama * FPS)))
    for i, a in enumerate(p["adegan"]):
        a["mulai"] = potong[i] / FPS
        a["durasi"] = (potong[i + 1] - potong[i]) / FPS
        a["kata"] = [{"t0": round(k["t0"] - a["mulai"], 3), "t1": round(k["t1"] - a["mulai"], 3), "teks": k["teks"]}
                     for k in kata[rentang[i][0]:rentang[i][1] + 1]]
        for lama in ("mp3", "durasi_suara"):
            a.pop(lama, None)
    p["narasi_mp3"] = _suara_mirip(p, narasi)
    mulai = potong[-1] / FPS
    p.pop("penutup", None)
    if o["disclaimer"] in ("akhir", "keduanya"):
        s = suara.bacakan(o["teks_disclaimer"], nama_suara, o["kecepatan"], nada, batal)
        if saya:
            s = {**s, "mp3": suara_saya.ubah(s["mp3"])}
        if o.get("suara_alami", True):
            s = {**s, "mp3": suara.manusiawikan(s["mp3"], s["kata"], o["teks_disclaimer"], batal)[0]}
            s["durasi"] = probe(s["mp3"])["durasi"]
        frames = int((s["durasi"] + 0.8) * render.FPS + 0.999)
        p["penutup"] = {"mp3": _suara_mirip(p, s["mp3"]), "durasi": frames / render.FPS, "mulai": round(mulai, 3)}
        mulai += frames / render.FPS
    p["total_durasi"] = round(mulai, 3)
    log(p, f"Narasi selesai: {int(mulai // 60)} menit {int(mulai % 60)} detik")


def _kandidat_dipakai(p):
    return [a["kandidat"][s[kunci]] for a in p["adegan"] for s in a.get("shots", []) for kunci in ("pilih", "stiker")
            if s.get(kunci) is not None and s[kunci] < len(a.get("kandidat") or [])] + \
        [k for a in p["adegan"] for k in _foto_banding(a)]


def _siapkan_banding(p, a, cfg, batal, judul_video):
    """Cari & unduh foto untuk perbandingan 🆚 (kiri = subjek kasusnya, kanan = tempat/benda pembanding)."""
    bd, o = a["banding"], p["opsi"]
    if bd.get("mode") == "satu_foto":
        return _siapkan_satu_foto(p, a, cfg, batal, judul_video)
    for sisi in ("kiri", "kanan"):
        info = bd[sisi]
        if info.get("bahan") and os.path.exists(info["bahan"]["file"]):
            continue
        log(p, f"  🆚 cari foto {sisi}: “{info['kueri']}” ({info['label']})")
        # Penilai AI diberi tahu persis apa yang harus tampak — narasi adegan saja terlalu longgar (pernah
        # memberi skor 7 untuk orang menyolder sebagai "lokasi latihan astronaut").
        syarat = (f"FOTO PERBANDINGAN “{info['label']}”: harus memperlihatkan {info['lihat']}. Foto orang yang "
                  f"sedang bekerja, peta, diagram, atau teks skor maksimal 3." if info.get("lihat") else
                  f"{info['label']}. {a['teks']}")
        kand = footage.urutkan_untuk_adegan(
            cfg, syarat, {"a": info["kueri"], "b": "", "c": ""}, o["format"], _dipakai(p),
            o["cek_gambar"], batal, log=lambda t: log(p, t), topik=(p.get("gambar_topik") or []) if sisi == "kiri" else (),
            judul=f"{info['label']} ({info['kueri']})", butuh=1)
        batas = footage.SKOR_BAGUS if o["cek_gambar"] else 0
        for k in [k for k in kand if k["jenis"] == "gambar" and (k.get("skor_ai") or 0) >= batas][:6]:
            try:
                bahan = footage.siapkan(k, 5.0, batal)
            except Dibatalkan:
                raise
            except Exception:
                bahan = None
            if bahan:
                info["k"], info["bahan"] = {x: k.get(x) for x in ("id", "sumber", "jenis", "url", "thumb", "halaman",
                                                                  "lisensi", "pembuat", "judul", "skor_ai", "isi_ai")}, bahan
                break
    bd["siap"] = all((bd[x] or {}).get("bahan") for x in ("kiri", "kanan"))
    if not bd["siap"]:
        log(p, "  🆚 foto perbandingan tidak lengkap — adegan ini memakai footage biasa")


def _siapkan_satu_foto(p, a, cfg, batal, judul_video):
    """🆚 "satu foto, dua dunia": SATU foto (misalnya pendaratan Apollo) dibuat versi Bulan dan versi Bumi —
    daratannya sama persis, latar & warnanya beda. Sisi olahan berlabel ILUSTRASI."""
    from . import lingkungan
    bd, o = a["banding"], p["opsi"]
    info = bd["kiri"]
    log(p, f"  🆚 satu foto, dua dunia: cari “{info['kueri']}”")
    syarat = (f"FOTO PERBANDINGAN: harus FOTO ASLI yang memperlihatkan {info['lihat']}, lengkap dengan daratan DAN "
              "langit/cakrawala yang jelas. Foto close-up tanpa langit, peta, diagram, atau teks skor maksimal 3. Foto "
              "latihan, simulasi, replika, maket, atau pajangan museum skor maksimal 2: sisi kiri berlabel "
              f"“{info['label']}” tanpa kata ilustrasi, jadi fotonya harus benar-benar itu.")
    # tanpa sumber web: fotonya diolah dan tampil besar, jadi harus resolusi asli tanpa watermark (foto web pernah
    # membawa tulisan "The Family Attic" dan cast biru hasil scan)
    kand = footage.urutkan_untuk_adegan(dict(cfg, sumber_web="tidak"), syarat, {"a": info["kueri"], "b": "", "c": ""},
                                        o["format"], _dipakai(p),
                                        o["cek_gambar"], batal, log=lambda t: log(p, t),
                                        topik=p.get("gambar_topik") or [], judul=f"{info['label']} ({info['kueri']})",
                                        butuh=1, lihat=syarat, subjek=info["kueri"])
    batas = footage.SKOR_BAGUS if o["cek_gambar"] else 0
    # foto NASA/Wikimedia/museum didahulukan: resolusi asli dan bebas watermark (foto web pernah membawa "The Family Attic")
    layak = [k for k in kand if k["jenis"] == "gambar" and (k.get("skor_ai") or 0) >= batas and k.get("sumber") != "Web"]
    layak.sort(key=lambda k: (k.get("sumber") == "Web", -(k.get("skor_ai") or 0)))
    # Sisi kiri diberi label sebagai foto ASLI ("BULAN, 1969"): foto latihan astronaut di hanggar pernah lolos dan
    # tampil berlabel Bulan. Metadata yang menyebut latihan/replika/museum dilewati, kecuali labelnya memang itu.
    bukan_asli = re.compile(r"\b(training|exercise|rehears\w*|simulat\w*|mock-?up|replica|museum|exhibit\w*|diorama|"
                            r"display|latihan|simulasi|replika|tiruan|maket|pameran)\b", re.I)
    if not bukan_asli.search(f"{info['label']} {info['lihat']} {info['kueri']}"):
        for k in [k for k in layak
                  if bukan_asli.search(f"{k.get('judul') or ''} {k.get('teks') or ''} {k.get('isi_ai') or ''}")
                  or footage._BUKAN_ASLI.search(k.get("isi_ai") or "")]:
            log(p, f"  🆚 “{(k.get('judul') or '')[:50]}” dilewati: bukan foto aslinya (latihan/replika/museum)")
            layak.remove(k)
    for k in layak[:6]:
        try:
            bahan = footage.siapkan(k, 5.0, batal)
        except Dibatalkan:
            raise
        except Exception:
            bahan = None
        if not bahan:
            continue
        if not lingkungan.ada_cakrawala(bahan["file"]):
            log(p, f"  🆚 “{(k.get('judul') or '')[:50]}” dilewati: tidak ada daratan dan langit yang jelas")
            continue
        hasil = {}
        for sisi in ("kiri", "kanan"):
            tujuan = PROYEK / p["id"] / f"banding-{sisi}.jpg"
            try:
                lingkungan.ubah(bahan["file"], bd[sisi].get("dunia", "asli"), tujuan, dari=bd["kiri"].get("dunia"))
                info_ = probe(tujuan)
            except Exception as e:
                log(p, f"  🆚 foto gagal diolah ({e})")
                hasil = {}
                break
            hasil[sisi] = {"file": str(tujuan), "jenis": "gambar", "mulai": 0, "lebar": info_["lebar"],
                           "tinggi": info_["tinggi"]}
        if hasil:
            ringkas = {x: k.get(x) for x in ("id", "sumber", "jenis", "url", "thumb", "halaman", "lisensi", "pembuat",
                                              "judul", "skor_ai", "isi_ai")}
            for sisi in ("kiri", "kanan"):
                bd[sisi]["k"], bd[sisi]["bahan"] = dict(ringkas), hasil[sisi]
            bd["kanan"]["k"]["judul"] = f"{k.get('judul')} (diolah jadi versi {bd['kanan'].get('dunia')}, ilustrasi)"
            break
    bd["siap"] = all((bd[x] or {}).get("bahan") for x in ("kiri", "kanan"))
    if not bd["siap"]:
        log(p, "  🆚 foto perbandingan tidak ketemu — adegan ini memakai footage biasa")


def _klip_layak(k, cek=True):
    """Klip boleh jadi latar shot: klip latar cadangan / pinjaman, atau latarnya cocok menurut AI."""
    return k["jenis"] == "video" and bool(k["id"]) and not k.get("gagal") and (
        not cek or k.get("cadangan") or k.get("pinjam") or footage.nilai_latar(k) >= footage.LATAR_BAGUS)


def _shot_layak(k):
    """Sisa kandidat (_kandidat_baru) yang masih pantas tampil di tata visual "video + stiker"."""
    if k["jenis"] == "video":
        return _klip_layak(k)
    return (k.get("skor_ai") or 0) >= 5 or (k.get("skor_ai") is None and bool(k.get("topik")))


def _boleh_dipinjam(k, cek=True):
    """Klip adegan lain dipakai untuk narasi yang berbeda: yang masih berlaku hanya kecocokan latarnya. Klip gajah
    (subjek 10 karena kata kunci analogi "1.600 gajah", latar 2) pernah dipinjam ke narasi tekanan air & sel."""
    if not cek or k.get("cadangan"):
        return True
    lat = k.get("skor_latar")
    return (lat if lat is not None else footage.nilai_latar(k)) >= footage.LATAR_BAGUS


def _kandidat_baru(kand, dipakai, sudah_dipakai, di_adegan_ini):
    """Kandidat terbaik yang belum dipakai — juga bukan foto kembar dari sumber lain (versi crop/resize)."""
    # kandidat analogi hanya untuk stiker tumpukan (foto pejabat untuk "telapak tangan" pernah tampil layar penuh)
    belum = [j for j, k in enumerate(kand) if (footage.identitas(k) not in dipakai or k.get("pinjam"))
             and not k.get("analogi") and not k.get("gagal")]
    # Urutan pilihan: TEPAT menurut AI (≥ SKOR_BAGUS) → gambar tepat yang sudah tampil di adegan ini diulang
    # (gerak kamera beda) → setema (5-6) → belum dinilai → sisanya. Lebih baik mengulang gambar yang tepat daripada
    # menampilkan gambar yang tidak nyambung dengan narasi.
    tepat = [j for j in belum if (kand[j].get("skor_ai") or 0) >= footage.SKOR_BAGUS]
    # sama tepatnya? yang lisensinya jelas (Wikimedia, museum, web berfilter lisensi) didahulukan dari gambar web biasa
    # klip video asli (+0,5) didahulukan dari foto yang sama tepatnya: gerakan nyata lebih hidup daripada foto
    tepat.sort(key=lambda j: -(kand[j]["skor_ai"] + 0.8 * footage.suasana(kand[j])
                               + (0.5 if kand[j].get("jenis") == "video" else 0)
                               - (0.6 if kand[j].get("lisensi") == "hak cipta milik pemiliknya" else 0)))
    for j in tepat[:10]:
        if kand[j].get("pinjam") and j not in di_adegan_ini:
            continue  # gambar pinjaman hanya cadangan terakhir (lihat di bawah)
        if not any(footage.sama_gambar(kand[j], lama) for lama in sudah_dipakai):
            return j
    ulang = [j for j in dict.fromkeys(di_adegan_ini) if j is not None and j < len(kand)
             and (kand[j].get("skor_ai") or 0) >= footage.SKOR_BAGUS]
    if ulang:
        return min(ulang, key=lambda j: di_adegan_ini.count(j))  # yang paling jarang tampil
    setema = [j for j in belum if (kand[j].get("skor_ai") or 0) >= 5 and not kand[j].get("pinjam")]
    if not setema:  # tidak ada satu pun yang layak: pakai gambar tepat dari adegan sebelumnya (gerak kamera beda)
        pinjam = [j for j in range(len(kand)) if kand[j].get("pinjam")]
        if pinjam:
            return pinjam[0]
    setema.sort(key=lambda j: -(kand[j]["skor_ai"] + 1.0 * footage.suasana(kand[j])))
    for j in setema[:10]:
        if not any(footage.sama_gambar(kand[j], lama) for lama in sudah_dipakai):
            return j
    # Yang setema ternyata kembaran gambar yang sudah tampil: ulangi gambar layak (≥5) dari adegan ini atau pinjam
    # gambar tepat adegan sebelumnya — dulu langsung jatuh ke kandidat yang belum dinilai (foto kastil Wales untuk
    # narasi "seluas 29 hektar").
    ulang = [j for j in dict.fromkeys(di_adegan_ini) if j is not None and j < len(kand)
             and (kand[j].get("skor_ai") or 0) >= 5]
    if ulang:
        return min(ulang, key=lambda j: di_adegan_ini.count(j))
    pinjam = [j for j in range(len(kand)) if kand[j].get("pinjam")]
    if pinjam:
        return pinjam[0]
    # belum dinilai: gambar dari artikel topik dulu (pasti tentang topiknya), baru hasil pencarian
    belum_dinilai = sorted((j for j in belum if kand[j].get("skor_ai") is None), key=lambda j: not kand[j].get("topik"))
    for kelompok in (belum_dinilai, belum):
        for j in kelompok[:10]:
            if not any(footage.sama_gambar(kand[j], lama) for lama in sudah_dipakai):
                return j
    if belum:
        return belum[0]
    lain = [j for j in range(len(kand)) if j not in di_adegan_ini]  # semua sudah terpakai: jangan ulang di adegan sama
    return lain[0] if lain else (0 if kand else None)


def _bagi_shot(a, total, n, minimum=1.5):
    """Bagi adegan jadi n shot. Pergantian gambar diletakkan di jeda antar-kata yang paling dekat dengan
    pembagian rata (jeda panjang lebih disukai), supaya gambar tidak berganti di tengah kata. Tiap shot minimal
    `minimum` detik (selama pembagian rata memungkinkan)."""
    if n <= 1:
        return [total]
    fps = render.FPS
    durasi = total / fps
    minimum = min(minimum, 0.9 * durasi / n)
    kata = a.get("kata") or []
    calon = [((x["t1"] + y["t0"]) / 2, y["t0"] - x["t1"]) for x, y in zip(kata, kata[1:])]
    batas, lalu = [], 0.0
    for k in range(1, n):
        ideal = durasi * k / n
        boleh = [c for c in calon if c[0] - lalu >= minimum and durasi - c[0] >= minimum * (n - k)]
        t = min(boleh, key=lambda c: abs(c[0] - ideal) - 2 * min(max(c[1], 0), 0.4))[0] if boleh else ideal
        batas.append(t)
        lalu = t
    frame = [0] + [round(t * fps) for t in batas] + [total]
    hasil = [b - a_ for a_, b in zip(frame, frame[1:])]
    if min(hasil) < 10:  # jaga-jaga: kembali ke pembagian rata
        dasar = total // n
        hasil = [dasar + (1 if i < total - dasar * n else 0) for i in range(n)]
    return hasil


def _fakta(p):
    """Video sains/fakta (bukan misteri/konspirasi): visual dokumenter cerah, tanpa perbandingan "MIRIP?"."""
    return p["opsi"].get("gaya_naskah") in naskah.GAYA_FAKTA


def _video_stiker(p):
    """Tata visual "video + stiker" (mode Re-create tetap memakai potongan video sumbernya seperti biasa)."""
    return p["opsi"].get("visual") == "video_stiker" and p["opsi"]["mode"] != "recreate"


_AWALAN_LABEL = re.compile(r"^(foto|gambar|lukisan|ilustrasi|ukiran|video|rekaman|potret|peta)\s+", re.I)
_EKOR_LABEL = re.compile(r"(\s+(di|ke|dari|yang|dan|atau|untuk|dengan|pada|of|the|in|and|at))+$", re.I)


def _label_stiker(subjek):
    """Label kuning di stiker dari subjek adegan ("foto pendaratan Apollo 11" → "PENDARATAN APOLLO 11")."""
    teks = _AWALAN_LABEL.sub("", " ".join((subjek or "").split()))
    if len(teks) > 28:
        teks = teks[:29].rsplit(" ", 1)[0]
    return _EKOR_LABEL.sub("", teks)


def _frames_foto(p, kecuali=None):
    """(frame foto layar penuh, total frame) di adegan yang sudah direncanakan — penjaga "mayoritas video"."""
    foto = total = 0
    for a in p["adegan"]:
        if a is kecuali:
            continue
        kand = a.get("kandidat") or []
        for s in a.get("shots", []):
            total += s["frames"]
            if s.get("banding") or (s.get("pilih") is not None and s["pilih"] < len(kand)
                                    and kand[s["pilih"]]["jenis"] != "video"):
                foto += s["frames"]
    return foto, total


def _latar_cadangan(p, i, cfg, kand):
    """Tidak ada klip yang pas: klip TEMPAT topiknya (dasar laut untuk lempeng Pasifik) sebagai latar, judulnya harus
    cocok dengan kueri; subjeknya tetap tampil lewat stiker foto yang tepat."""
    kueri = _kueri_latar(p, i)
    if not kueri and not _fakta(p):  # proyek misteri lama: suasana kelam umum masih pas
        kueri = [naskah.cadangan(False)[i % 10]]
    # kandidat adegan lain juga dikecualikan: klip tempat yang sudah habis dipotong adegan lain tidak membantu
    kecuali = {k["id"] for k in kand} | {k["id"] for b in p["adegan"] for k in (b.get("kandidat") or [])}
    q_cad, cad = footage.klip_latar(cfg, kueri, p["opsi"]["format"], kecuali, p["adegan"][i]["teks"],
                                    log=lambda t: log(p, t))
    if cad:
        log(p, f"  Tidak ada klip yang pas — {len(cad)} klip tempat “{q_cad}” disiapkan sebagai latar")
    else:
        log(p, "  Tidak ada klip yang pas — memakai klip adegan terdekat & foto ≤3 detik")
    return cad


def _kueri_latar(p, i):
    """Kueri klip latar (tempat di dunia topik video) dari kata kunci AI: adegan i dulu, lalu adegan terdekat."""
    hasil = []
    for j in sorted(range(len(p["adegan"])), key=lambda j: (abs(j - i), j > i)):
        q = ((p["adegan"][j].get("q") or {}).get("latar") or "").strip()
        if q and q not in hasil:
            hasil.append(q)
    return hasil


def _rencana_lemah(a):
    """Rencana adegan yang masih kosong, tanpa klip, mengulang satu foto berkali-kali (peta Guam 5x @2 detik), atau
    satu take panjang karena klipnya cuma satu (stasiun bawah laut 14 detik)."""
    pilih = [s.get("pilih") for s in a["shots"] if not s.get("banding")]
    klip = sum(1 for j in pilih if j is not None and a["kandidat"][j]["jenis"] == "video")
    return None in pilih or (klip == 0 and a["durasi"] > 2 * footage.MAKS_FOTO) or len(set(pilih)) < len(pilih) / 2 \
        or any(s["frames"] > 8 * render.FPS for s in a["shots"])


def _rencanakan(p, a, i, cfg, frames_adegan):
    """Rencana shot tata "video + stiker". Kalau klip yang nyambung sudah habis dipakai adegan lain, dicari klip
    tempat yang belum tampil dulu; kandidat yang dinilai tidak nyambung baru dipakai kalau itu pun gagal."""
    a["shots"] = _rencana_video(p, a, i, frames_adegan)
    if not p["opsi"]["cek_gambar"] or not _rencana_lemah(a):
        return
    if not a.get("latar_dicari"):
        a["latar_dicari"] = True
        cad = _latar_cadangan(p, i, cfg, a["kandidat"])
        if cad:
            a["kandidat"] = (cad + [k for k in a["kandidat"] if not k.get("pinjam")])[:22]
            a["shots"] = _rencana_video(p, a, i, frames_adegan)
    if any(s.get("pilih") is None and not s.get("banding") for s in a["shots"]):
        a["shots"] = _rencana_video(p, a, i, frames_adegan, ketat=False)


def _rencana_video(p, a, i, frames_adegan, ketat=True):
    """Tata visual "video + stiker" (meniru video referensi pengguna): potongan ±3,5 detik yang hampir semuanya klip
    video; foto yang TEPAT menurut AI ditempel sebagai stiker di atas klip; foto layar penuh hanya kalau perlu dan
    maksimal 3 detik. Urutan pilihan latar tiap shot: klip adegan ini yang layak (setema ke atas) → potongan lain
    dari klip yang sama (tidak berturut-turut) → klip cadangan suasana → klip adegan sebelumnya yang masih punya
    potongan → foto layar penuh ≤3 detik → cadangan lama (_kandidat_baru)."""
    o = p["opsi"]
    kand = a["kandidat"]
    fps = render.FPS
    maks_foto = int(footage.MAKS_FOTO * fps)
    cek = o["cek_gambar"]
    dipakai, sudah_dipakai = _dipakai(p), _kandidat_dipakai(p)
    for s in a.get("shots", []):  # rencana lama adegan ini tidak dihitung
        for kunci in ("pilih", "stiker"):
            if s.get(kunci) is not None and s[kunci] < len(kand):
                dipakai.discard(footage.identitas(kand[s[kunci]]))
    pakai = _pakai_klip(p, a.get("shots", []))
    jumlah = footage.jumlah_shot(a["durasi"], o["format"], video=True)
    durasi_shot = a["durasi"] / jumlah

    def nilai(j):
        k = kand[j]
        return (footage.nilai_latar(k) + 0.6 * footage.suasana(k) + 0.15 * (k.get("skor_h") or 0)
                - (4 if k.get("cadangan") else 0) - (5 if k.get("pinjam") else 0))

    klip = sorted((j for j, k in enumerate(kand) if _klip_layak(k, cek)), key=lambda j: -nilai(j))
    sendiri = sum(1 for j in klip if not kand[j].get("pinjam"))
    # Pinjam dulu, baru potongan ditentukan: dulu adegan "tanpa klip" dipotong ±2,6 detik ala foto lalu klip
    # pinjaman mengisi potongan sependek 1,9 detik.
    if i > 0 and (sendiri == 0 or (sendiri < 2 and jumlah >= 3)):
        # klip adegan ini kurang dari 2 untuk ≥3 potongan (atau tidak ada sama sekali): pinjam klip adegan sebelumnya
        # (masih satu bahasan) yang potongannya belum habis, daripada satu klip jadi satu take 15 detik
        for b in reversed(p["adegan"][:i]):
            for s in b.get("shots", []):
                kb = (b.get("kandidat") or [])[s["pilih"]] if s.get("pilih") is not None and \
                    s["pilih"] < len(b.get("kandidat") or []) else None
                if kb and kb["jenis"] == "video" and not kb.get("gagal") and _boleh_dipinjam(kb, cek) and \
                        len(pakai.get(footage.identitas(kb), ())) < footage.maks_bagian(kb, durasi_shot) and \
                        not any(footage.identitas(x) == footage.identitas(kb) for x in kand):
                    kand.append({**kb, "pinjam": True})
                    klip.append(len(kand) - 1)
            if len(klip) >= 2:
                break

    def tepat(j):
        k = kand[j]
        if k["jenis"] == "video" or k.get("pinjam") or k.get("analogi") or k.get("gagal") \
                or footage.identitas(k) in dipakai:
            return False
        if cek:
            return (k.get("skor_ai") or 0) >= footage.SKOR_BAGUS
        return bool(k.get("topik")) or (bool(a["q"].get("a")) and k.get("kueri") == a["q"].get("a"))

    foto = sorted((j for j in range(len(kand)) if tepat(j)),
                  key=lambda j: -((kand[j].get("skor_ai") or 0) + (0.8 if kand[j].get("topik") else 0)
                                  + 0.5 * footage.suasana(kand[j])))
    ada_klip = bool(klip)
    if not ada_klip:
        # Tanpa klip sama sekali: tiap foto yang pas tampil sekali, lebih lama (tetap ada zoom/pan). Dulu dipotong
        # ±2,6 detik sehingga satu peta Guam tampil 5x berturut-turut @2 detik.
        jumlah = max(1, min(math.ceil(a["durasi"] / (footage.MAKS_FOTO - 0.4)), len(foto)))
    potong = _bagi_shot(a, frames_adegan, jumlah, minimum=footage.MIN_SHOT_VIDEO)
    banding = (a.get("banding") or {}).get("siap")
    if banding and potong[0] - maks_foto >= fps:  # perbandingan 🆚 = dua foto, jadi ikut batas 3 detik
        potong = [maks_foto, potong[0] - maks_foto] + potong[1:]
    durasi_shot = frames_adegan / fps / len(potong)
    foto_layar, total_layar = _frames_foto(p, kecuali=a)
    shots, antre, lalu = [], list(potong), None
    if i > 0 and p["adegan"][i - 1].get("shots"):
        b = p["adegan"][i - 1]
        s = b["shots"][-1]
        if s.get("pilih") is not None and s["pilih"] < len(b.get("kandidat") or []):
            lalu = footage.identitas(b["kandidat"][s["pilih"]])

    di_adegan = {}  # identitas klip → berapa kali tampil di adegan ini

    def ambil_klip(boleh_lalu=False):
        for ulang in (False, True):  # klip yang belum tampil dulu, baru potongan lain dari klip yang sudah tampil
            for j in klip:
                idn = footage.identitas(kand[j])
                n = len(pakai.get(idn, ()))
                if (idn == lalu and not boleh_lalu) or (n > 0) != ulang \
                        or n >= footage.maks_bagian(kand[j], durasi_shot) \
                        or di_adegan.get(idn, 0) >= 2:
                    continue
                if not ulang and idn in dipakai and not kand[j].get("pinjam"):
                    continue
                return j
        return None

    def perpanjang(tambah):
        """Shot sebelumnya dibuat lebih panjang (satu take utuh), daripada memotong klip yang sama berkali-kali."""
        shots[-1]["frames"] += tambah

    # Aturan supaya tidak "patah-patah" (berlaku untuk topik apa pun): tidak ada shot di bawah 2,5 detik, klip yang
    # sama tidak pernah berurutan (diperpanjang jadi satu take), dan klip yang sama paling banyak 2x per adegan.
    # Dulu klip pantai yang sama dipotong 5-7x berturut-turut ±2 detik, dan foto/klip berselang-seling tiap 1,7 detik.
    minim = int(2.5 * fps)
    while antre:
        f = antre.pop(0)
        nomor = len(shots)
        if banding and nomor == 0:
            shots.append({"frames": f, "pilih": None, "bahan": None, "banding": True})
            continue
        # Sesekali foto tepat yang sangat kuat tampil layar penuh (seperti potongan dokumen/foto di video
        # referensi), selama total foto layar penuh masih di bawah 25% video.
        kuat = nomor == 1 and len(potong) >= 3 and foto and (kand[foto[0]].get("skor_ai") or 0) >= 8 and \
            foto_layar + min(f, maks_foto) <= 0.25 * (total_layar + frames_adegan)
        j = None if kuat else ambil_klip()
        if j is None and foto:
            j = foto.pop(0)
        if j is None and cek and not shots:
            j = ambil_klip(boleh_lalu=True)  # lanjutkan klip penutup adegan sebelumnya (potongan lain)
        if j is None:
            j = _kandidat_baru(kand, dipakai, sudah_dipakai, [s["pilih"] for s in shots])
            # Sisa kandidat yang dinilai tidak nyambung (pohon kelapa & jalan kota untuk narasi dasar Palung Mariana):
            # klip sebelumnya diperpanjang saja, walaupun jadi satu take panjang. Shot pertama dibiarkan kosong supaya
            # _rencanakan mencari klip tempat dulu.
            if j is not None and cek and ketat and not _shot_layak(kand[j]) and (
                    not shots or shots[-1].get("pilih") is None or kand[shots[-1]["pilih"]]["jenis"] == "video"):
                j = None
        if j is None:
            if shots:
                perpanjang(f)
            else:
                shots.append({"frames": f, "pilih": None, "bahan": None})
            continue
        k = kand[j]
        idn = footage.identitas(k)
        if shots and idn == lalu:  # cadangan menunjuk klip yang barusan tampil: sambung saja, jangan dipotong
            perpanjang(f)
            continue
        if k["jenis"] != "video" and f > maks_foto + 3 and ada_klip:
            # foto layar penuh maksimal 3 detik; sisanya jadi potongan berikutnya kalau ≥2,5 detik, kalau tidak
            # ditambahkan ke klip sebelumnya / potongan berikutnya (tidak ada potongan sependek 1,7 detik lagi)
            sisa = f - maks_foto
            f = maks_foto
            if sisa >= minim:
                antre.insert(0, sisa)
            elif shots and shots[-1].get("pilih") is not None and kand[shots[-1]["pilih"]]["jenis"] == "video":
                perpanjang(sisa)
            elif antre:
                antre[0] += sisa
            else:
                f += sisa
        s = {"frames": f, "pilih": j, "bahan": None}
        if k["jenis"] == "video":
            s["bagian"] = _bagian_bebas(p, k, pakai=pakai)
            pakai.setdefault(idn, set()).add(s["bagian"])
            di_adegan[idn] = di_adegan.get(idn, 0) + 1
            lalu = idn
        else:
            foto_layar += f
            lalu = None
        if j in foto:
            foto.remove(j)
        dipakai.add(idn)
        sudah_dipakai.append(k)
        shots.append(s)

    t, n = a["mulai"], 0
    layak_stiker = []  # shot klip yang cukup lama dan tidak tertutup judul hook di ±3 detik pertama video
    for s in shots:
        mulai, t = t, t + s["frames"] / fps
        kb = kand[s["pilih"]] if s.get("pilih") is not None else None
        if kb and kb["jenis"] == "video" and s["frames"] >= 1.5 * fps and mulai + s["frames"] / fps >= 3.5:
            layak_stiker.append(s)
    # Analogi ("setara dengan menumpuk 1.600 gajah"): foto benda pembandingnya ditumpuk di shot klip pertama.
    analogi = next((j for j, k in enumerate(kand) if k.get("analogi") and footage.identitas(k) not in dipakai), None)
    if analogi is not None and layak_stiker:
        s = layak_stiker[0]
        s["stiker"], s["tumpuk"] = analogi, int(a["q"].get("jumlah") or 0)
        dipakai.add(footage.identitas(kand[analogi]))
    # Stiker foto tepat: shot klip ke-1, ke-3, … selama fotonya ada.
    for n, s in enumerate(layak_stiker):
        if n % 2 or s.get("stiker") is not None:
            continue
        while foto:
            j = foto.pop(0)
            if not any(footage.sama_gambar(kand[j], lama) for lama in sudah_dipakai):
                s["stiker"] = j
                dipakai.add(footage.identitas(kand[j]))
                sudah_dipakai.append(kand[j])
                break
    return shots


def _subjek(p):
    """Nama topik dalam bahasa Inggris (judul artikel Wikipedia hasil riset), misalnya "Loch Ness Monster"."""
    riset_ = p.get("riset") or []
    return next((s["judul"] for s in riset_ if s.get("lang") == "en"), "") or (riset_[0]["judul"] if riset_ else "")


def _kunci_spesifik(kunci, p):
    """Kata kunci a menyebut hal tertentu (bukan sekadar nama subjek utama seperti "Giant")."""
    kata = {k for k in re.findall(r"\w+", (kunci or "").lower()) if len(k) > 2}
    subjek = {k for k in re.findall(r"\w+", _subjek(p).lower())}
    return bool(kata - subjek - {"mythological", "mythology", "legend", "legendary", "painting", "ancient"})


def _artikel_bukti(p):
    """Judul artikel riset selain artikel utama (bukti, tempat, benda, legenda terkait)."""
    return [s["judul"] for s in p.get("riset") or [] if s.get("terkait") and s.get("lang", "en") == "en"]


def _nama_diri(teks):
    """Kata berhuruf besar yang bukan awal kalimat (nama tempat/tokoh: "Ontario", "Nanabozho")."""
    nama = []
    for kalimat in re.split(r"(?<=[.!?])\s+", teks):
        kata = re.findall(r"[^\W\d_][\w'-]*", kalimat)
        nama += [k for k in kata[1:] if k[0].isupper()]
    return nama


def _lengkapi_artikel(p, teks_adegan, q):
    """Periksa penanda artikel bukti per adegan. AI pernah menandai adegan Bixi sebagai "Giant jars of Assam" dan
    adegan Sleeping Giant sebagai "Maushop", jadi urutan kepercayaannya:
    1) adegan menyebut nama khas judul artikel (awalan 5 huruf: "garam Himalaya" ~ "Himalayan salt");
    2) nama diri di adegan (misalnya "Nanabozho") muncul di isi artikel;
    3) penanda AI dipakai hanya kalau adegan itu lanjutan adegan sebelumnya yang membahas artikel yang sama."""
    terkait = {s["judul"]: s for s in p.get("riset") or [] if s.get("terkait") and s.get("lang", "en") == "en"}
    utama = {k[:5] for k in re.findall(r"\w+", _subjek(p).lower())}
    # Nama yang ada di artikel utama (Gigantes, Uranus) milik topik utama, bukan bukti tertentu: tanpa ini
    # "Gigantes" ~ "gigantic" menyeret adegan mitologi Yunani ke artikel "Leonardo's crossbow".
    isi_utama = {k[:5] for s in p.get("riset") or [] if not s.get("terkait") for k in re.findall(r"\w+", s["teks"].lower())}
    khas, isi_artikel = {}, {}
    for judul, s in terkait.items():
        kata = {k[:5] for k in re.findall(r"\w+", re.sub(r"\(.*?\)", "", judul).lower()) if len(k) >= 4} - utama
        if kata:
            khas[judul] = kata
        isi_artikel[judul] = {k[:5] for k in re.findall(r"\w+", s["teks"].lower())}
    sebelumnya = set()  # artikel yang disebut/dipakai adegan sebelumnya
    for t, qq in zip(teks_adegan, q):
        ai = qq.get("artikel") or ""
        kata = {k[:5] for k in re.findall(r"\w+", t.lower())}
        judul_cocok = [j for j in khas if khas[j] & kata]
        skor = {}  # wajib per adegan: dulu hanya diisi di cabang lain → crash kalau adegan pertama cocok judul
        if judul_cocok:
            pilih = ai if ai in judul_cocok else max(judul_cocok, key=lambda j: len(khas[j] & kata))
        else:
            nama = {k[:5].lower() for k in _nama_diri(t) if len(k) >= 5} - utama - isi_utama
            skor = {j: len(nama & isi_artikel[j]) for j in terkait if nama & isi_artikel[j]}
            if skor:
                pilih = ai if ai in skor else max(skor, key=skor.get)
            else:
                skor = {}
                pilih = ai if ai and ai in sebelumnya else ""
        if pilih:
            qq["artikel"] = pilih
        else:
            qq.pop("artikel", None)
        sebelumnya = {pilih, *judul_cocok, *skor} - {""}
    ditandai = sum(1 for qq in q if qq.get("artikel"))
    if ditandai:
        log(p, f"{ditandai} adegan membahas bukti/artikel tertentu — footage-nya diambil dari artikel itu")


def l_footage(p, cfg, batal):
    o = p["opsi"]
    n = len(p["adegan"])
    gagal_unduh = set()  # kandidat yang gagal tidak dicoba lagi di shot lain
    if not p.get("riset"):  # mode "bacakan": cari artikel topiknya untuk gambar topik
        p["riset"] = riset.kumpulkan(cfg, p["naskah"][:1500], batal, log=lambda t: log(p, t))
    # Kata kunci baru untuk adegan yang belum punya ("Cari ulang footage"), atau yang hanya meminjam kata kunci
    # tetangganya karena AI sempat gagal (misalnya Ollama mati sesaat) — selama footage-nya belum dicari.
    ulang = [a for a in p["adegan"] if not a.get("kandidat") and
             (not a.get("q") or a["q"].get("pinjam_q") or "lihat" not in a["q"])]
    if ulang:
        log(p, f"AI membuat ulang kata kunci footage untuk {len(ulang)} adegan…")
        q = naskah.kata_kunci_adegan(cfg, p["meta"].get("judul") or p["nama"], [a["teks"] for a in ulang],
                                     batal, log=lambda t: log(p, t), subjek=_subjek(p), artikel=_artikel_bukti(p),
                                     fakta=_fakta(p))
        _lengkapi_artikel(p, [a["teks"] for a in ulang], q)
        for a, qq in zip(ulang, q):
            a["q"] = qq
    if o["mode"] == "recreate":
        _footage_recreate(p)
    if "gambar_topik" not in p:
        p["gambar_topik"] = footage.gambar_topik(p.get("riset") or [], log=lambda t: log(p, t))
    judul_video = " — ".join(x for x in (p["meta"].get("judul"), _subjek(p)) if x)
    video = _video_stiker(p)
    for i, a in enumerate(p["adegan"]):
        batal.cek()
        p["pesan"] = f"Footage adegan {i + 1}/{n}"
        _progres(p, "footage", i / n)
        if not a.get("kandidat"):
            art = a["q"].get("artikel")
            log(p, f"Adegan {i + 1}: cari “{a['q'].get('a') or '-'}” / “{a['q'].get('b')}” / “{a['q'].get('c') or '-'}”"
                   + (f" · gambar dari artikel “{art}”" if art else ""))
            # Adegan yang membahas satu bukti (misalnya Bixi): gambar "pasti nyambung" diambil dari artikel bukti
            # itu, bukan dari artikel topik utama (yang isinya lukisan raksasa umum).
            topik_adegan = footage.gambar_artikel("en", art, log=lambda t: log(p, t)) if art else []
            kand = footage.urutkan_untuk_adegan(cfg, a["teks"], a["q"], o["format"], _dipakai(p),
                                               o["cek_gambar"], batal, log=lambda t: log(p, t),
                                               topik=topik_adegan or p["gambar_topik"], judul=judul_video,
                                               butuh=footage.jumlah_shot(a["durasi"], o["format"], video=video),
                                               lihat=a["q"].get("lihat", ""), subjek=a["q"].get("subjek", ""),
                                               spesifik=bool(art) or _kunci_spesifik(a["q"].get("a"), p),
                                               video=video, cerah=o["gaya"] == "cerah")
            if len(kand) < 2:  # kata kunci terlalu spesifik: tambah suasana tempat topiknya
                kand += footage.urutkan_untuk_adegan(cfg, a["teks"], {"a": "", "b": (_kueri_latar(p, i) or [
                    naskah.cadangan(_fakta(p))[i % 10]])[0]}, o["format"], _dipakai(p), False, batal, video=video,
                    cerah=o["gaya"] == "cerah")
            if video:
                # klip yang layak dulu (AI hanya melihat sebagian), lalu foto & sisanya: 20 kandidat pertama disimpan
                kand.sort(key=lambda k: -(footage.nilai_latar(k) + (1 if k["jenis"] == "video" else 0)))
                if not any(_klip_layak(k, o["cek_gambar"]) for k in kand):
                    kand = _latar_cadangan(p, i, cfg, kand) + kand
            if video and a["q"].get("analogi"):
                # "setara dengan menumpuk 1.600 gajah": foto benda pembandingnya jadi stiker bertumpuk
                kand = footage.kandidat_analogi(cfg, a["q"]["analogi"], a["teks"], o["cek_gambar"], batal,
                                                log=lambda t: log(p, t))[:2] + kand
            a["kandidat"] = kand[:22]
        if a.get("banding") and not a["banding"].get("siap"):
            _siapkan_banding(p, a, cfg, batal, judul_video)
        frames_adegan = int(round(a["durasi"] * render.FPS))
        if video and (not a.get("shots") or sum(s["frames"] for s in a["shots"]) != frames_adegan):
            _rencanakan(p, a, i, cfg, frames_adegan)
            jenis = [a["kandidat"][s["pilih"]]["jenis"] if s.get("pilih") is not None else "🆚" if s.get("banding")
                     else "-" for s in a["shots"]]
            log(p, f"  {len(a['shots'])} potongan: {jenis.count('video')} klip, {jenis.count('gambar')} foto ≤3 dtk"
                   f"{', ' + str(sum(1 for s in a['shots'] if s.get('stiker') is not None)) + ' stiker' if any(s.get('stiker') is not None for s in a['shots']) else ''}")
        elif not a.get("shots") or sum(s["frames"] for s in a["shots"]) != frames_adegan:
            jumlah = footage.jumlah_shot(a["durasi"], o["format"])
            if o["cek_gambar"]:
                # Lebih baik sedikit shot dengan gambar yang pas (tiap gambar tampil lebih lama, tetap ada
                # efek zoom/pan) daripada mengisi shot dengan gambar ber-skor rendah. Maksimal 15 detik per shot.
                bagus = sum(1 for k in a["kandidat"] if k.get("skor_ai", 0) >= footage.SKOR_BAGUS)
                jumlah = min(jumlah, max(bagus, math.ceil(a["durasi"] / 15), 1))
            if a["kandidat"] and all(k.get("sumber") == "Video sumber" for k in a["kandidat"]):
                jumlah = 1  # potongan video sumber diputar terus sepanjang adegan
            dipakai = _dipakai(p)
            sudah_dipakai = _kandidat_dipakai(p)
            # yang dihitung hanya kandidat yang MASIH BISA dipakai (belum tampil di adegan lain): dulu kandidat bagus
            # yang sudah terpakai ikut dihitung, cadangan tidak dibuat, lalu foto roket yang belum dinilai muncul
            # untuk narasi "bendera berkibar"
            tersedia = [k for k in a["kandidat"] if not k.get("pinjam") and footage.identitas(k) not in dipakai]
            if i > 0 and not any((k.get("skor_ai") or 0) >= 5 for k in tersedia):
                # Adegan tanpa satu pun gambar yang layak: siapkan gambar terbaik adegan sebelumnya sebagai cadangan
                # (dulu jatuh ke kandidat yang belum dinilai, misalnya foto roket untuk narasi "pantulan di kamera").
                lalu = p["adegan"][i - 1]
                terbaik = [lalu["kandidat"][s["pilih"]] for s in lalu.get("shots", [])
                           if s.get("pilih") is not None and s["pilih"] < len(lalu.get("kandidat") or [])
                           and (lalu["kandidat"][s["pilih"]].get("skor_ai") or 0) >= footage.SKOR_BAGUS]
                if terbaik and not any(k.get("pinjam") for k in a["kandidat"]):
                    a["kandidat"].append({**terbaik[0], "pinjam": True})
                    log(p, f"  Adegan {i + 1}: tidak ada gambar yang pas — memakai ulang gambar adegan sebelumnya")
            shots = []
            for f in _bagi_shot(a, frames_adegan, jumlah):
                pilih = _kandidat_baru(a["kandidat"], dipakai, sudah_dipakai, [s["pilih"] for s in shots])
                if pilih is not None:
                    dipakai.add(footage.identitas(a["kandidat"][pilih]))
                    sudah_dipakai.append(a["kandidat"][pilih])
                shots.append({"frames": f, "pilih": pilih, "bahan": None})
            a["shots"] = shots
        if (a.get("banding") or {}).get("siap") and a["shots"] and not any(s.get("banding") for s in a["shots"]):
            a["shots"][0]["banding"] = True  # shot pertama adegan ini = perbandingan 🆚
        rencana_ulang, j = 0, 0
        while j < len(a["shots"]):
            s = a["shots"][j]
            j += 1
            batal.cek()
            if s.get("stiker") is not None and not (s.get("stiker_bahan") and os.path.exists(s["stiker_bahan"]["file"])):
                _unduh_stiker(p, a, s, gagal_unduh, batal)
            if s.get("banding") or (s.get("bahan") and os.path.exists(s["bahan"]["file"])):
                continue
            s["bahan"] = None
            kand = a["kandidat"]
            # Pilihan perencana gagal diunduh / layarnya hitam: adegan direncanakan ulang tanpa kandidat itu. Dulu
            # diganti kandidat berikutnya apa saja (tetesan air di semak & foto pejabat untuk narasi Palung Mariana).
            ulang = video and o["cek_gambar"] and s.get("pilih") is not None and rencana_ulang < 4
            if ulang:
                coba = [s["pilih"]] if kand[s["pilih"]]["id"] not in gagal_unduh else []
            else:
                coba = [s["pilih"]] if s.get("pilih") is not None else []
                dipakai = _dipakai(p)
                coba += [x for x in range(len(kand)) if x not in coba and footage.identitas(kand[x]) not in dipakai]
                coba = [x for x in coba if kand[x]["id"] not in gagal_unduh]
                if video:  # cadangan untuk shot video: klip lain dulu (foto layar penuh maksimal 3 detik)
                    coba = coba[:1] + sorted(coba[1:], key=lambda x: kand[x]["jenis"] != "video"
                                             and s["frames"] > footage.MAKS_FOTO * render.FPS)
            for x in coba[:6]:
                k = kand[x]
                try:
                    if k.get("file"):  # upload sendiri
                        info = probe(k["file"])
                        bahan = {"file": k["file"], "jenis": k["jenis"], "mulai": k.get("mulai", 0),
                                 "lebar": info["lebar"], "tinggi": info["tinggi"],
                                 "tutup_bawah": bool(k.get("tutup_bawah"))}
                    else:
                        bagian = 0
                        if k["jenis"] == "video":
                            bagian = s.get("bagian", 0) if x == s.get("pilih") else _bagian_bebas(p, k, kecuali=s)
                        bahan = footage.siapkan(k, s["frames"] / render.FPS, batal, bagian=bagian)
                        if bahan and k["jenis"] == "video":
                            s["bagian"] = bagian
                except Dibatalkan:
                    raise
                except Exception as e:
                    log(p, f"  {k['sumber']} gagal diambil: {e}")
                    bahan = None
                if bahan:
                    s["pilih"], s["bahan"] = x, bahan
                    break
                gagal_unduh.add(k["id"])
                log(p, f"  {k['sumber']} “{(k.get('judul') or k.get('isi_ai') or '')[:50]}” tidak bisa diunduh"
                       + (", adegan direncanakan ulang" if ulang else ", coba kandidat lain"))
            if not s["bahan"] and ulang:
                kand[s["pilih"]]["gagal"] = True
                rencana_ulang += 1
                _rencanakan(p, a, i, cfg, frames_adegan)
                j = 0
                continue
            if not s["bahan"]:
                s["gagal"] = True
                log(p, f"  Adegan {i + 1} shot {j}: tidak ada footage yang bisa dipakai — pakai latar gelap")
    _progres(p, "footage", 1)


def _unduh_stiker(p, a, s, gagal_unduh, batal):
    """Unduh foto stiker satu shot; gagal → foto tepat lain yang belum tampil, atau shot itu tanpa stiker."""
    kand = a["kandidat"]
    dipakai = _dipakai(p)
    lain = [x for x, k in enumerate(kand) if x != s["stiker"] and k["jenis"] != "video" and not k.get("pinjam")
            and (k.get("skor_ai") or 0) >= footage.SKOR_BAGUS and footage.identitas(k) not in dipakai]
    for x in [s["stiker"]] + lain[:3]:
        k = kand[x]
        if k["id"] in gagal_unduh:
            continue
        try:
            if k.get("file"):
                info = probe(k["file"])
                bahan = {"file": k["file"], "jenis": k["jenis"], "lebar": info["lebar"], "tinggi": info["tinggi"]}
            else:
                bahan = footage.siapkan(k, footage.MAKS_FOTO, batal)
        except Dibatalkan:
            raise
        except Exception:
            bahan = None
        if bahan and bahan["jenis"] == "gambar":
            if k.get("potongan") and os.path.exists(k["potongan"]):  # benda analogi tanpa latar (gunungan gajah)
                bahan["potongan"] = k["potongan"]
            s["stiker"], s["stiker_bahan"] = x, bahan
            return
        gagal_unduh.add(k["id"])
    log(p, f"  Stiker “{(kand[s['stiker']].get('judul') or '')[:40]}” tidak bisa diunduh — shot ini tanpa stiker")
    s["stiker"] = None
    s.pop("stiker_bahan", None)


_GAMBAR_DATAR = re.compile(r"\b(peta|map|maps|diagram|skema|schematic|grafik|graph|chart|infografis|infographic|"
                           r"penampang|cross-?section|sketch|sketsa|ilustrasi|illustration|batimetri|bathymetr\w*|"
                           r"dokumen|document|teks|text|tabel|table|lukisan|painting|poster|logo|ikon|icon)\b", re.I)


def _foto_hidup(p, s, nomor, gerak, batal, k=None):
    """Opsi animasi "hidup": foto dijadikan klip 2.5D parallax (benda depan bergerak terpisah dari latar), bukan
    zoom/pan biasa. Gagal (model belum ada, foto rusak) → foto apa adanya untuk zoom/pan.
    k = kandidatnya: peta/diagram/dokumen/lukisan (dari judul atau isi menurut AI) tidak dipisah jadi lapisan."""
    o, bahan = p["opsi"], s["bahan"]
    datar = bool(k) and bool(_GAMBAR_DATAR.search(f"{k.get('judul') or ''} {k.get('isi_ai') or ''}"))
    if o.get("animasi", "hidup") != "hidup" or bahan["jenis"] != "gambar" or not hidup.tersedia():
        return bahan
    W, H = render.UKURAN[o["format"]]
    sw, sh = bahan.get("lebar") or W, bahan.get("tinggi") or H
    if o["isi_layar"] == "blur" and max(sw / sh, W / H) / min(sw / sh, W / H) > 1.25:
        return bahan  # mode "tampil utuh, pinggir blur" tetap memakai zoompan
    try:
        klip = hidup.animasikan(bahan["file"], s["frames"] + 16, W, H,
                                gerak or render._GILIRAN_GERAK[nomor % len(render._GILIRAN_GERAK)],
                                fps=render.FPS, tutup_bawah=bool(bahan.get("tutup_bawah")), batal=batal, datar=datar)
        return {"jenis": "video", "file": str(klip), "mulai": 0, "lebar": W, "tinggi": H}
    except Dibatalkan:
        raise
    except Exception as e:
        log(p, f"  Foto 2.5D gagal ({type(e).__name__}: {str(e)[:80]}); pakai zoom/pan biasa")
        return bahan


_POSE_URUTAN = re.compile(r"^\W*(pertama|kedua|ketiga|keempat|kelima|terakhir)\b", re.I)
_POSE_KAGET = re.compile(r"\b(ternyata|luar biasa|mengejutkan|bayangkan|wow|raksasa|terbesar|tertua|terdalam)\b", re.I)
_POSE_SENANG = re.compile(r"^\W*(jadi|intinya|itulah)\b", re.I)


def _acara_maskot(p, ada_hook):
    """Kapan maskot muncul dan dengan pose apa: {(adegan, shot): {"pose", "tunda", "durasi"}}.
    Pembuka (kaget, bersama judul hook), urutan "Pertama/Kedua…" (nunjuk), pertanyaan (mikir), fakta mengejutkan
    (kaget), rangkuman "Jadi…" (senang), ajakan di akhir (melambai). Paling sering sekali tiap ±9 detik, dan tidak di
    shot yang sedang menampilkan stiker supaya layar tidak penuh."""
    hasil, terakhir, n = {}, -99.0, len(p["adegan"])
    for i, a in enumerate(p["adegan"]):
        teks = a["teks"].strip()
        if i == 0:
            pose = "kaget" if ada_hook else "melambai"
        elif i == n - 1:
            pose = "melambai"
        elif _POSE_URUTAN.search(teks):
            pose = "nunjuk"
        elif _POSE_SENANG.search(teks):
            pose = "senang"
        elif "?" in teks:
            pose = "mikir"
        elif _POSE_KAGET.search(teks):
            pose = "kaget"
        else:
            continue
        if a["mulai"] - terakhir < 9 and i != n - 1:
            continue
        t = a["mulai"]
        for j, s in enumerate(a["shots"]):
            durasi_shot = s["frames"] / render.FPS
            if durasi_shot >= 1.6 and not s.get("stiker_bahan") and not s.get("banding") and s.get("bahan"):
                hasil[(i, j)] = {"pose": pose, "tunda": 0.15, "durasi": round(min(2.8, durasi_shot - 0.3), 2)}
                terakhir = t
                break
            t += durasi_shot
    return hasil


def _teks_layar(p, ada_hook):
    """Angka/istilah kunci tiap adegan yang tampil besar ±2 detik (gaya cerah). Di atas layar kalau shot pertama
    adegan itu menampilkan stiker; adegan pembuka dilewati kalau sudah ada judul hook."""
    hasil = []
    for i, a in enumerate(p["adegan"]):
        teks = (a.get("q") or {}).get("teks_layar", "").strip()
        if not teks or (i == 0 and ada_hook) or a["durasi"] < 1.6:
            continue
        t0 = a["mulai"] + 0.25
        stiker = bool(a["shots"]) and bool(a["shots"][0].get("stiker_bahan"))
        hasil.append({"teks": teks, "t0": round(t0, 2), "t1": round(t0 + min(2.3, a["durasi"] - 0.5), 2),
                      "atas": stiker})
    return hasil


def l_render(p, cfg, batal):
    o = p["opsi"]
    kerja = PROYEK / p["id"] / "render"
    kerja.mkdir(parents=True, exist_ok=True)
    shots, nomor = [], 0
    total_shot = sum(len(a["shots"]) for a in p["adegan"])
    # transisi, gerak kamera, suasana, dan aksen suara tiap adegan dipilih dari isinya (efek.rencana)
    berefek = o["gaya"] in ("misterius", "cerah")
    rencana = efek.rencana(p["adegan"], o["gaya"]) if berefek else [{} for _ in p["adegan"]]
    ada_hook = berefek and bool(p["meta"].get("teks_thumbnail"))
    muncul_stiker = []  # detik munculnya stiker & maskot (diberi bunyi "pop")
    gambar_maskot = {}
    if o.get("maskot") and maskot.tersedia():
        try:
            gambar_maskot = maskot.siapkan()
        except Exception as e:
            log(p, f"Maskot gagal disiapkan ({e}); video tanpa maskot")
    acara = _acara_maskot(p, ada_hook) if gambar_maskot else {}
    for i, a in enumerate(p["adegan"]):
        t_shot = a["mulai"]
        for j, s in enumerate(a["shots"]):
            batal.cek()
            mulai_shot, t_shot = t_shot, t_shot + s["frames"] / render.FPS
            stiker = None
            if s.get("stiker_bahan") and os.path.exists(s["stiker_bahan"]["file"]):
                # judul hook memenuhi layar ±3 detik pertama: stiker menunggu sampai judulnya hilang
                tunda = max(0.12, 3.05 - mulai_shot) if ada_hook else 0.12
                if s["frames"] / render.FPS - tunda >= 1.0:
                    tumpuk = int(s.get("tumpuk") or 0)
                    # stiker analogi: labelnya jumlahnya ("×1.600"), bukan subjek adegan
                    label = (f"×{tumpuk:,}".replace(",", ".") if tumpuk > 1 else "") if "tumpuk" in s else \
                        _label_stiker(a["q"].get("subjek"))
                    stiker = {"file": s["stiker_bahan"]["file"], "label": label, "tunda": tunda, "tumpuk": tumpuk,
                              "potongan": s["stiker_bahan"].get("potongan")}
            muncul = acara.get((i, j))
            maskot_shot = {**muncul, "file": gambar_maskot[muncul["pose"]]} if muncul else None
            tujuan = kerja / f"shot-{i:03d}-{j}.mp4"
            if tujuan.exists():
                tujuan.unlink()
            try:
                if s.get("banding") and (a.get("banding") or {}).get("siap"):
                    bd = a["banding"]
                    render.buat_shot_banding(bd["kiri"]["bahan"], bd["kanan"]["bahan"], bd["kiri"]["label"],
                                             bd["kanan"]["label"], s["frames"], o["format"], o["gaya"], nomor, tujuan,
                                             batal, transisi=rencana[i].get("transisi") if j == 0 else None,
                                             sama=bd.get("mode") == "satu_foto")
                elif s.get("bahan"):
                    # transisi hanya di shot pertama tiap adegan; gerak khusus (hentak/goyang) juga di shot pertama
                    transisi = rencana[i].get("transisi") if j == 0 else None
                    gerak = rencana[i].get("gerak") if j == 0 else None
                    bahan = _foto_hidup(p, s, nomor, gerak, batal, k=a["kandidat"][s["pilih"]] if
                                        s.get("pilih") is not None and s["pilih"] < len(a["kandidat"]) else None)
                    if transisi == "zoom" and bahan["jenis"] == "video":
                        transisi = "kilat"  # zoom tembus dikerjakan zoompan, yang hanya dipakai untuk foto
                    try:
                        render.buat_shot(bahan, s["frames"], o["format"], o["gaya"], o["isi_layar"], nomor, tujuan,
                                         batal, transisi=transisi, gerak=gerak, stiker=stiker, maskot=maskot_shot)
                        muncul_stiker += [mulai_shot + x["tunda"] for x in (stiker, maskot_shot) if x]
                    except RuntimeError as e:
                        if not (stiker or maskot_shot):
                            raise
                        log(p, f"  Stiker/maskot shot {i + 1}.{j + 1} gagal ditempel ({str(e)[:80]}); shot polos")
                        render.buat_shot(bahan, s["frames"], o["format"], o["gaya"], o["isi_layar"], nomor, tujuan,
                                         batal, transisi=transisi, gerak=gerak)
                else:
                    render.shot_kosong(s["frames"], o["format"], tujuan, batal, gaya=o["gaya"])
            except Dibatalkan:
                raise
            except RuntimeError as e:
                log(p, f"  Shot {i + 1}.{j + 1} gagal dirender ({e}); pakai latar gelap")
                render.shot_kosong(s["frames"], o["format"], tujuan, batal, gaya=o["gaya"])
            shots.append(tujuan)
            nomor += 1
            p["pesan"] = f"Render shot {nomor}/{total_shot}"
            _progres(p, "render", 0.75 * nomor / total_shot)
    penutup = p.get("penutup")
    if penutup:  # kartu disclaimer di akhir: latar gelap, teksnya lewat subtitle
        tujuan = kerja / "shot-penutup.mp4"
        render.shot_kosong(int(round(penutup["durasi"] * render.FPS)), o["format"], tujuan, batal, gaya=o["gaya"])
        shots.append(tujuan)
    log(p, "Menggabungkan video, narasi, musik, dan subtitle…")
    musik = render.pilih_musik() if o["musik"] else None
    if o["musik"] and not musik:
        jenis = "dokumenter tenang" if o["gaya"] == "cerah" else "misteri"
        log(p, f"Folder musik/ kosong — pakai musik {jenis} bawaan (taruh .mp3 di folder musik untuk musik sendiri)")
        try:
            musik = efek.musik_cerah() if o["gaya"] == "cerah" else efek.musik_misteri()
        except Exception as e:
            log(p, f"Musik bawaan gagal dibuat: {e}")
    sfx = None
    if berefek:  # suara transisi, suasana latar, dan aksen sesuai isi tiap adegan
        try:
            info = [{"mulai": a["mulai"], "durasi": a["durasi"], **r} for a, r in zip(p["adegan"], rencana)]
            banding = [a["mulai"] + 0.5 for a in p["adegan"]
                       if a.get("shots") and a["shots"][0].get("banding") and (a.get("banding") or {}).get("siap")]
            sfx = efek.jalur_sfx(info, p["total_durasi"], kerja / "sfx.wav", banding=banding, stiker=muncul_stiker)
        except Exception as e:
            log(p, f"Efek suara gagal dibuat: {e}")
    # Subtitle per adegan; audio = satu narasi utuh (+ kartu disclaimer di akhir).
    adegan_render = [{"durasi": a["durasi"], "mulai": a["mulai"], "kata": a.get("kata", [])} for a in p["adegan"]]
    akhir_utama = p["adegan"][-1]["mulai"] + p["adegan"][-1]["durasi"]
    suara_render = [{"mp3": p["narasi_mp3"], "durasi": round(akhir_utama, 3)}]
    if penutup:
        adegan_render.append({**penutup, "kata": []})
        suara_render.append({"mp3": penutup["mp3"], "durasi": penutup["durasi"]})
    disclaimer = {"awal": o["teks_disclaimer"] if o["disclaimer"] in ("awal", "keduanya") else "",
                  "akhir": (penutup["mulai"], penutup["durasi"], o["teks_disclaimer"]) if penutup else None}
    judul = p["meta"].get("judul") or p["nama"]
    folder = OUTPUT / f"{p['id'][:8]}-{slug(judul, 50)}"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / f"{slug(judul, 50)}.mp4"
    render.gabung(kerja, shots, adegan_render, p["total_durasi"], o["format"], o["subtitle"], musik,
                  o["volume_musik"], video, batal, disclaimer=disclaimer, suara=suara_render,
                  geser_kata=0.0 if p.get("waktu_whisper") else render.GESER_KATA,
                  hook=p["meta"].get("teks_thumbnail", "") if berefek else "", sfx=sfx, gaya_visual=o["gaya"],
                  layar=_teks_layar(p, ada_hook) if o["gaya"] == "cerah" else (),
                  logo=gambar_maskot.get("logo"))
    _progres(p, "render", 0.95)
    dv = render.durasi_video(video)
    if abs(dv - p["total_durasi"]) > 0.1:
        log(p, f"⚠️ Durasi gambar {dv:.2f} dtk ≠ suara {p['total_durasi']:.2f} dtk — kemungkinan tidak sinkron")
    else:
        log(p, f"Cek sinkron: gambar {dv:.2f} dtk = suara {p['total_durasi']:.2f} dtk ✓")
    if not render.audio_utuh(video):
        log(p, "⚠️ Audio video punya bagian yang terlewat (paket melar) — coba Render ulang")
    else:
        log(p, "Cek audio: utuh, tidak ada bagian narasi yang terlewat ✓")

    # Thumbnail: utamakan foto subjek spesifik (kata kunci "a") dengan skor AI tinggi yang tidak terlalu gelap.
    calon = []
    for a in p["adegan"]:
        for s in a["shots"]:
            if s.get("bahan"):
                k = a["kandidat"][s["pilih"]]
                spesifik = bool(a["q"].get("a")) and k.get("kueri") == a["q"].get("a")
                nilai = (k.get("skor_ai") or 4) + (2 if spesifik else 0) + (1 if s["bahan"]["jenis"] == "gambar" else 0)
                calon.append((nilai, s["bahan"]))
            if s.get("stiker_bahan") and s.get("stiker") is not None:  # foto stiker = subjek yang tepat
                calon.append(((a["kandidat"][s["stiker"]].get("skor_ai") or 4) + 2.5, s["stiker_bahan"]))
    calon.sort(key=lambda x: -x[0])
    thumb = folder / "thumbnail.jpg"
    try:
        pilihan = None
        for _, bahan in calon[:6]:
            detik = bahan.get("mulai", 0) + 1 if bahan["jenis"] == "video" else 0
            if render.kecerahan(bahan["file"], detik) >= 45:
                pilihan = (bahan, detik)
                break
        if not pilihan and calon:
            bahan = calon[0][1]
            pilihan = (bahan, bahan.get("mulai", 0) + 1 if bahan["jenis"] == "video" else 0)
        if pilihan:
            bahan, detik = pilihan
            sumber_thumb = bahan["file"]
            if bahan["jenis"] == "video":
                sumber_thumb = kerja / "frame-thumb.jpg"
                ffmpeg(["-ss", f"{detik:.2f}", "-i", bahan["file"], "-frames:v", "1", str(sumber_thumb)], timeout=60)
            render.thumbnail(kerja, sumber_thumb, p["meta"].get("teks_thumbnail", ""), o["format"], thumb)
    except RuntimeError as e:
        log(p, f"Thumbnail gagal: {e}")

    (folder / "naskah.txt").write_text(p["naskah"], encoding="utf-8")
    (folder / "deskripsi.txt").write_text(_deskripsi(p), encoding="utf-8")
    p["hasil"] = {"folder": str(folder), "video": str(video), "thumbnail": str(thumb) if thumb.exists() else "",
                  "durasi": p["total_durasi"]}
    log(p, f"Selesai! {video.name}")


def _deskripsi(p):
    m = p["meta"]
    tags = m.get("tags", [])
    o = p["opsi"]
    baris = [m.get("judul", ""), "", m.get("deskripsi", ""), ""]
    if o.get("mode") in ("teaser", "recreate"):  # reels/short: arahkan ke video lengkapnya
        link = _link_induk(p)
        baris += [f"▶️ Video lengkapnya: {link}" if link else "▶️ Video lengkapnya ada di channel ini.", ""]
    if o.get("disclaimer", "awal") != "tidak":
        baris += ["⚠️ Disclaimer: " + (o.get("teks_disclaimer") or config.DISCLAIMER_BAWAAN), ""]
    bab = _chapter(p)
    if bab:
        baris += ["Daftar isi:"] + bab + [""]
    baris += [" ".join("#" + t.replace(" ", "") for t in tags[:8]), "", "TAGS: " + ", ".join(tags), ""]
    if p.get("riset"):
        baris += ["Bahan riset:"] + [f"- {s['url']}" for s in p["riset"]] + [""]
    baris.append("Sumber footage:")
    lihat = set()
    for a in p["adegan"]:
        dipakai_adegan = [a["kandidat"][s["pilih"]] for s in a.get("shots", [])
                          if s.get("bahan") and s.get("pilih") is not None and not s.get("banding")]
        dipakai_adegan += [a["kandidat"][s["stiker"]] for s in a.get("shots", [])
                           if s.get("stiker_bahan") and s.get("stiker") is not None]
        if any(s.get("banding") for s in a.get("shots", [])):
            dipakai_adegan += _foto_banding(a)
        for k in dipakai_adegan:
            if k["id"] in lihat or k.get("file"):
                continue
            lihat.add(k["id"])
            nama = " ".join(str(k.get("judul") or k["sumber"]).split())[:120]
            pembuat = " ".join(str(k.get("pembuat") or "").split())[:80]
            pembuat = f" oleh {pembuat}" if pembuat else ""
            baris.append(f"- {nama}{pembuat} ({k['sumber']}, {k.get('lisensi', '')}) {k.get('halaman') or ''}".strip())
    return "\n".join(baris) + "\n"


def _anak_reels(p):
    """Id reels milik video panjang ini (proyek lama hanya punya satu "kembar_id")."""
    ids = list(p.get("reels") or ([p["kembar_id"]] if p.get("kembar_id") else []))
    return [i for i in ids if i in _proyek]


def _isi_reels(p, anak, nomor, fokus):
    """Siapkan satu proyek reels teaser dari naskah video panjang p (dipanggil dengan _lock)."""
    o = p["opsi"]
    anak["opsi"].update(format="9:16", mode="teaser", kembar=False, durasi=o["durasi_reels"],
                        gaya_naskah=o["gaya_naskah"], cta=o["cta_reels"])
    anak["nama"] = f"[Reels {nomor}] {p['nama']}"[:80]
    anak["sumber_teks"] = p["naskah"]
    anak["sudut"], anak["reels_ke"], anak["induk"] = fokus, nomor, p["id"]
    anak["riset"] = p.get("riset", [])
    anak["selesai"], anak["naskah"] = ["riset"], ""
    anak["adegan"], anak["meta"], anak["bab"] = [], {}, []
    for kunci in ("gambar_topik", "narasi_mp3", "kembar_id"):
        anak.pop(kunci, None)
    anak["status"], anak["galat"], anak["pesan"] = "antri", "", "Menunggu giliran"
    anak["antri_sejak"] = _sekarang()
    _simpan(anak, paksa=True)


def _buat_reels(p, cfg, batal):
    """Format "keduanya": setelah naskah video panjang final, rencanakan beberapa reels teaser dengan fokus berbeda
    lalu antrikan. Kalau naskahnya ditulis ulang, reels yang sudah ada ikut dibuat ulang (yang berlebih dihapus)."""
    p.pop("kembar_segarkan", None)
    n = p["opsi"]["jumlah_reels"]
    log(p, f"AI merencanakan {n} reels teaser dengan fokus berbeda…")
    fokus = naskah.rencana_reels(cfg, p["naskah"], n, batal, log=lambda t: log(p, t))
    lama = _anak_reels(p)
    with _lock:
        # Restart (mati lampu) sesudah reels dibuat tapi sebelum video panjang tersimpan: reels itu tetap ada dengan
        # induk = video ini, jadi dipakai ulang, bukan dibuat lagi (Sahara pernah punya 6 reels).
        lama += sorted((i for i, a in _proyek.items() if a.get("induk") == p["id"] and i not in lama
                        and a["opsi"].get("mode") == "teaser"), key=lambda i: _proyek[i]["dibuat"])
    for pid in lama[n:]:
        hapus(pid)
    ids = []
    for i, f in enumerate(fokus):
        with _lock:
            anak = _proyek[lama[i]] if i < len(lama) else buat(p["naskah"], {**p["opsi"], "format": "9:16"})
            _isi_reels(p, anak, i + 1, f)
        ids.append(anak["id"])
        log(p, f"  📱 Reels {i + 1}: {f}")
    p["reels"] = ids
    p.pop("kembar_id", None)
    _simpan(p, paksa=True)
    _bangun.set()


def atur_link(pid, link):
    """Link video panjang (setelah diupload) dipasang di deskripsi semua reels-nya."""
    link = " ".join(str(link or "").split())[:300]
    if link and not re.match(r"^https?://\S+$", link):
        raise ValueError("Link harus diawali http:// atau https://")
    with _lock:
        p = _proyek.get(pid)
        if not p:
            raise KeyError(pid)
        p["link_video"] = link
        anak = [_proyek[i] for i in _anak_reels(p)]
    _simpan(p, paksa=True)
    for a in anak:  # reels yang sudah jadi: deskripsi.txt langsung diperbarui, tidak perlu render ulang
        folder = Path(a.get("hasil", {}).get("folder") or "")
        if a.get("status") == "selesai" and folder.is_dir():
            (folder / "deskripsi.txt").write_text(_deskripsi(a), encoding="utf-8")
    return p


def _link_induk(p):
    induk = _proyek.get(p.get("induk") or "")
    return (induk or {}).get("link_video", "")


# ---------------------------------------------------------------- mode re-create

def buat_recreate(sumber, tema, jumlah, opsi, rc):
    """Beberapa short dari SATU video panjang. sumber = {"jenis": "proyek", "id"} (video dari aplikasi ini) atau
    {"jenis": "file", "path", "nama"} (video milik pengguna). tema = satu short per tema; kosong = AI memilih
    `jumlah` tema dari transkrip."""
    if sumber.get("jenis") == "proyek":
        src = _proyek.get(sumber.get("id") or "")
        if not src or not src.get("adegan") or not src.get("hasil", {}).get("video"):
            raise ValueError("Pilih video panjang yang sudah selesai dibuat")
        sumber = {"jenis": "proyek", "id": src["id"], "nama": src["meta"].get("judul") or src["nama"]}
    else:
        path = Path(sumber.get("path") or "")
        if not path.is_file():
            raise ValueError("File video sumber tidak ditemukan")
        sumber = {"jenis": "file", "path": str(path), "nama": sumber.get("nama") or path.stem}
    tema = [" ".join(t.split())[:300] for t in tema if t and t.strip()][:8]
    n = len(tema) or max(1, min(8, int(jumlah or 3)))
    rc = {"gaya_short": "mandiri" if rc.get("gaya_short") == "mandiri" else "teaser",
          "samakan_suara": bool(rc.get("samakan_suara", True)), "izin": bool(rc.get("izin")),
          "tutup_bawah": bool(rc.get("tutup_bawah"))}
    opsi = {**opsi, "format": "9:16", "mode": "recreate", "kembar": False}
    if sumber["jenis"] == "proyek" and rc["samakan_suara"]:  # pengisi suara sama persis dengan video panjangnya
        opsi.update({k: src["opsi"][k] for k in ("suara", "kecepatan", "nada")})
    hasil = []
    for i in range(n):
        judul = tema[i] if tema else f"tema pilihan AI ke-{i + 1}"
        ekstra = {"recreate": {**rc, "sumber": sumber, "tema": tema[i] if tema else "", "tema_ke": i, "jumlah": n}}
        if sumber["jenis"] == "proyek":
            ekstra["induk"] = sumber["id"]  # tombol "Lihat video panjang" + link-nya di deskripsi
        hasil.append(buat(f"Re-create: {judul}", opsi, nama=f"[Short {i + 1}] {sumber['nama']}", ekstra=ekstra))
    return hasil


def _siapkan_recreate(p, cfg, batal):
    rc, s = p["recreate"], p["recreate"]["sumber"]
    if s["jenis"] == "proyek":
        src = _proyek.get(s["id"])
        if not src:
            raise RuntimeError("Proyek video panjang sumbernya sudah dihapus")
        p["transkrip"] = recreate.transkrip_proyek(src)
        p["riset"] = src.get("riset") or []
        o = p["opsi"]
        log(p, f"Sumber: “{s['nama']}” ({len(p['transkrip'])} adegan). Suara: {o['suara']} {o['kecepatan']:+d}% "
               f"{o['nada']:+d}Hz" + (" (sama dengan video panjangnya)" if rc["samakan_suara"] else ""))
    else:
        path = s["path"]
        if not os.path.exists(path):
            raise RuntimeError("File video sumber tidak ditemukan")
        p["transkrip"] = recreate.transkrip_file(path, log=lambda t: log(p, t), batal=batal)
        if not p["transkrip"]:
            raise RuntimeError("Tidak ada ucapan yang terdengar di video sumber")
        if rc["samakan_suara"]:
            a = recreate.analisa_suara(path, p["transkrip"])
            p["opsi"].update(suara=a["suara"], nada=a["nada"], kecepatan=a["kecepatan"])
            log(p, f"Suara sumber: {'wanita' if a['wanita'] else 'pria'}, nada ±{a['f0']} Hz, {a['kata_per_detik']} "
                   f"kata/detik → {a['suara']} {a['kecepatan']:+d}% {a['nada']:+d}Hz")
            if rc["izin"] and suara_mirip.tersedia():
                p["suara_ref"] = recreate.referensi_suara(path, p["transkrip"])
                log(p, "Warna suara akan disamakan dengan pembicara di video sumber (OpenVoice)")
            elif rc["izin"]:
                log(p, "OpenVoice belum terpasang — suara hanya disamakan jenis, nada, dan kecepatannya")
        if p["opsi"]["riset"]:  # gambar topik untuk adegan yang tidak ada padanannya di video sumber
            p["riset"] = riset.kumpulkan(cfg, recreate.teks_transkrip(p["transkrip"], 1500), batal,
                                         log=lambda t: log(p, t))
    if not rc.get("tema"):
        rc["tema"] = _tema_otomatis(p, cfg, batal)
        log(p, f"Tema pilihan AI: {rc['tema']}")


def _tema_otomatis(p, cfg, batal):
    """Tema berbeda untuk tiap short dari sumber yang sama (direncanakan sekali, dipakai semua short-nya)."""
    rc, s = p["recreate"], p["recreate"]["sumber"]
    berkas = recreate.FOLDER / f"tema-{hash_pendek(json.dumps([s.get('id') or s.get('path'), rc['jumlah']]))}.json"
    if berkas.exists():
        rencana = json.loads(berkas.read_text(encoding="utf-8"))
    else:
        recreate.FOLDER.mkdir(parents=True, exist_ok=True)
        rencana = naskah.rencana_reels(cfg, recreate.teks_transkrip(p["transkrip"]), rc["jumlah"], batal,
                                       log=lambda t: log(p, t))
        berkas.write_text(json.dumps(rencana, ensure_ascii=False), encoding="utf-8")
    return rencana[min(rc["tema_ke"], len(rencana) - 1)]


def _suara_mirip(p, mp3):
    """Re-create dari file milik pengguna (sudah menyatakan izin): warna suara narasi disamakan dengan sumber."""
    if not (p.get("suara_ref") and (p.get("recreate") or {}).get("izin") and suara_mirip.tersedia()):
        return mp3
    tujuan = Path(mp3).with_name(f"{Path(mp3).stem}-mirip-{hash_pendek('|'.join(p['suara_ref']))}.wav")
    if not tujuan.exists():
        log(p, "Menyamakan warna suara dengan video sumber (OpenVoice)…")
        suara_mirip.samakan(mp3, p["suara_ref"], tujuan)
    return str(tujuan)


def _footage_recreate(p):
    """Visual tiap adegan diambil dari bagian sumber yang membahas hal yang sama. Sumber proyek: gambar asli
    adegannya (dirender ulang ke 9:16, tanpa subtitle lama). Sumber file: potongan videonya."""
    rc, tr = p["recreate"], p.get("transkrip") or []
    s = rc["sumber"]
    src = _proyek.get(s.get("id") or "") if s["jenis"] == "proyek" else None
    dapat = 0
    for a in p["adegan"]:
        if a.get("kandidat"):
            continue
        cocok = recreate.cocokkan(a["teks"], tr)
        if not cocok:
            continue
        if src:
            kand, lihat = [], set()
            for j in range(cocok[0], cocok[1] + 1):
                sa = src["adegan"][tr[j]["adegan"]]
                semua = sa.get("kandidat") or []
                dipilih = [semua[x["pilih"]] for x in sa.get("shots", [])
                           if x.get("pilih") is not None and x["pilih"] < len(semua)]
                for k in dipilih + [k for k in semua if (k.get("skor_ai") or 0) >= footage.SKOR_BAGUS]:
                    if footage.identitas(k) not in lihat and not k.get("pinjam"):
                        lihat.add(footage.identitas(k))
                        kand.append({**k, "skor_ai": max(k.get("skor_ai") or 0, footage.SKOR_BAGUS)})
            if kand:
                a["kandidat"] = kand[:12]
                dapat += 1
        else:
            k = recreate.klip_sumber(s["path"], tr, cocok, s["nama"])
            k["tutup_bawah"] = rc.get("tutup_bawah", False)
            a["kandidat"] = [k]
            dapat += 1
    log(p, f"{dapat} dari {len(p['adegan'])} adegan memakai visual dari video sumber"
           + ("" if dapat == len(p["adegan"]) else "; sisanya dicari dari sumber footage biasa"))


def _waktu(detik):
    detik = int(detik)
    j, m, d = detik // 3600, detik % 3600 // 60, detik % 60
    return f"{j}:{m:02d}:{d:02d}" if j else f"{m:02d}:{d:02d}"


def _chapter(p):
    """Chapter YouTube dari bab naskah panjang: cari adegan tempat tiap bab dimulai."""
    if p["opsi"]["format"] != "16:9" or len(p.get("bab") or []) < 3:
        return []
    norm = lambda t: " ".join(re.findall(r"\w+", t.lower()))
    baris, cari_dari = [], 0
    for i, b in enumerate(p["bab"]):
        kunci = " ".join(norm(b["awal"]).split()[:5])
        for j in range(cari_dari, len(p["adegan"])):
            if kunci and kunci in norm(p["adegan"][j]["teks"]):
                waktu = 0 if i == 0 else p["adegan"][j].get("mulai", 0)
                if not baris or waktu - baris[-1][0] >= 10:  # syarat YouTube: tiap chapter minimal 10 detik
                    baris.append((waktu, b["judul"]))
                cari_dari = j + 1
                break
    if len(baris) < 3 or baris[0][0] != 0:
        return []
    return [f"{_waktu(t)} {judul}" for t, judul in baris]


FUNGSI = {"riset": l_riset, "naskah": l_naskah, "adegan": l_adegan, "suara": l_suara, "footage": l_footage,
          "render": l_render}


def kerjakan(p):
    cfg = config.muat()
    batal = Batal()
    with _lock:
        _batal[p["id"]] = batal
        p["status"] = "jalan"
        p["galat"] = ""
    try:
        for langkah in LANGKAH:
            if langkah in p["selesai"]:
                continue
            batal.cek()
            if langkah == "adegan" and p["opsi"].get("kembar") and (not _anak_reels(p) or p.get("kembar_segarkan")):
                _buat_reels(p, cfg, batal)
            p["langkah"] = langkah
            _progres(p, langkah)
            FUNGSI[langkah](p, cfg, batal)
            p["selesai"].append(langkah)
            _progres(p, langkah)
            _simpan(p, paksa=True)
            if langkah == "naskah" and p["opsi"]["cek_naskah"] and p["opsi"]["mode"] == "tulis":
                p["selesai"].remove("naskah")  # ditandai selesai lagi saat pengguna klik Lanjut
                with _lock:
                    p["status"] = "cek_naskah"
                    p["pesan"] = "Naskah siap diperiksa — edit kalau perlu, lalu klik Lanjut"
                return
        with _lock:
            p["status"] = "selesai"
            p["progres"] = 100
            p["langkah"] = ""
    except Dibatalkan:
        with _lock:
            p["status"] = "dibatalkan"
            p["pesan"] = "Dibatalkan"
    except Exception as e:
        traceback.print_exc()
        with _lock:
            p["status"] = "gagal"
            p["galat"] = str(e) or type(e).__name__  # beberapa error tidak punya pesan (NoBackendError)
        log(p, f"GAGAL di langkah {p.get('langkah')}: {p['galat']}")
    finally:
        with _lock:
            _batal.pop(p["id"], None)
            for fungsi, antri in _tertunda.pop(p["id"], []):
                _terapkan(p, fungsi, antri, True)
        _simpan(p, paksa=True)


def _pekerja():
    while True:
        with _lock:
            # Urut waktu MASUK antrean (bukan waktu dibuat): video lama yang dicari ulang footage-nya tidak
            # menyerobot reels yang sudah menunggu.
            antri = sorted((p for p in _proyek.values() if p["status"] == "antri"),
                           key=lambda p: p.get("antri_sejak") or p["dibuat"])
        if antri:
            kerjakan(antri[0])
            continue
        _bangun.wait(timeout=15)
        _bangun.clear()
        _pantau_input()


def _pantau_input():
    cfg = config.muat()
    if not cfg.get("pantau_input"):
        return
    selesai = INPUT / "sudah-diproses"
    for f in sorted(INPUT.glob("*.txt")):
        try:
            if time.time() - f.stat().st_mtime < 5:  # file mungkin masih ditulis
                continue
            mentah = f.read_bytes()
            try:
                teks = mentah.decode("utf-8-sig")
            except UnicodeDecodeError:
                teks = mentah.decode("cp1252", "replace")
            if teks.strip():
                buat(teks, cfg["default"], nama=f.stem)
            selesai.mkdir(exist_ok=True)
            shutil.move(str(f), str(selesai / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{f.name}"))
        except Exception:
            traceback.print_exc()


def mulai_pekerja():
    muat_semua()
    threading.Thread(target=_pekerja, daemon=True, name="pekerja-video").start()
