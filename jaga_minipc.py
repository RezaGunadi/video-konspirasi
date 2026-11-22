# -*- coding: utf-8 -*-
"""Jaga mini PC A/B/C biar TIDAK NGANGGUR, dgn prioritas user: REGEN > generate baru > nonton.
Tiap mini PC yg proyek aktif (jalan+antri) < AMBANG diisi:
  1) REGEN video lokal yg belum di-upload & rawan footage (cari-ulang) dari rahasia/regen_backlog.json
  2) kalau backlog regen habis -> topik BARU dari rahasia/topik_cadangan.json
  3) kalau dua-duanya habis -> andalkan NONTON (auto-play, di luar skrip ini)
Resumable: rahasia/regen_done.json. Dijadwalkan tiap 2 jam (Task "JagaMiniPC").
  .venv\\Scripts\\python.exe jaga_minipc.py              # top-up kalau idle
  .venv\\Scripts\\python.exe jaga_minipc.py --status      # cek saja
  .venv\\Scripts\\python.exe jaga_minipc.py --seed 6      # paksa antre 6 regen/PC skrg (kick off)
"""
import sys, json, argparse
from pathlib import Path
from datetime import datetime
import requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent; RAH = ROOT / "rahasia"
CAD = RAH / "topik_cadangan.json"; LOG = RAH / "jaga_minipc.log"
BACKLOG = RAH / "regen_backlog.json"; DONE = RAH / "regen_done.json"
PC = ["http://192.168.100.63:3220", "http://192.168.100.54:3220", "http://192.168.100.71:3220"]
AMBANG = 2
TERM = {"selesai", "dibatalkan", "gagal", "error", ""}
OPSI = {
 "mode":"tulis","format":"16:9","durasi":300,"suara":"saya","kecepatan":-5,"nada":0,
 "subtitle":True,"musik":True,"volume_musik":12,"cek_gambar":True,"gen_gambar":True,
 "cek_naskah":False,"riset":True,"gaya":"cerah","isi_layar":"crop","gaya_naskah":"sains",
 "suara_alami":True,"animasi":"hidup","visual":"video_stiker","maskot":True,
 "cta":"Tulis di komentar topik mana lagi yang bikin kamu penasaran, dan subscribe biar nggak ketinggalan.",
 "jumlah_reels":1,"durasi_reels":45,
 "cta_reels":"Jawaban lengkapnya ada di video panjangnya. Tonton lewat link di bawah.","disclaimer":"tidak",
}
def log(t):
    s = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {t}"; print(s, flush=True)
    try: LOG.open("a", encoding="utf-8").write(s + "\n")
    except Exception: pass
def jget(p, d):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return d
def aktif(base):
    pr = requests.get(base + "/api/proyek", timeout=8).json().get("proyek", [])
    return sum(1 for p in pr if (p.get("status") or "") not in TERM)

def regen_satu(base, backlog, done):
    """cari-ulang 1 proyek backlog milik base yg belum done. True kalau berhasil antre."""
    for x in backlog:
        if x["pc"] != base or x["pid"] in done: continue
        pid = x["pid"]
        try:
            r = requests.post(f"{base}/api/proyek/{pid}/cari-ulang", json={}, timeout=30)
            if r.status_code == 404:
                done.add(pid); log(f"{base}: regen {pid} -> proyek tak ada (skip)"); return "skip"
            r.raise_for_status(); done.add(pid)
            log(f"{base}: REGEN antre {pid} ({x['file'][:40]})"); return True
        except Exception as e:
            log(f"{base}: regen {pid} GAGAL {str(e)[:50]}"); return False
    return None  # backlog habis utk pc ini

def topik_baru(base, cad):
    if not cad: return None
    ambil = cad[:6]; del cad[:6]
    try:
        requests.post(base + "/api/proyek", json={"teks":"\n".join(ambil),"opsi":OPSI,"per_baris":True}, timeout=30)
        log(f"{base}: generate BARU antre {len(ambil)} topik (cadangan sisa {len(cad)})"); return True
    except Exception as e:
        cad[:0] = ambil; log(f"{base}: generate baru GAGAL {str(e)[:50]}"); return False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--status", action="store_true"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    backlog = jget(BACKLOG, []); done = set(jget(DONE, [])); cad = jget(CAD, [])
    sisa_regen = sum(1 for x in backlog if x["pid"] not in done)
    log(f"--- jaga: backlog regen sisa {sisa_regen}/{len(backlog)}, cadangan topik {len(cad)} ---")
    for base in PC:
        try: n = aktif(base)
        except Exception as e: log(f"{base}: TAK TERHUBUNG ({str(e)[:40]})"); continue
        if a.status: log(f"{base}: aktif={n}"); continue
        if a.seed:
            ok = 0
            while ok < a.seed:
                r = regen_satu(base, backlog, done)
                if r is None: log(f"{base}: backlog regen habis"); break
                if r is True: ok += 1
            continue
        if n >= AMBANG: log(f"{base}: aktif={n} (cukup)"); continue
        # prioritas: regen -> topik baru -> nonton
        r = regen_satu(base, backlog, done)
        while r == "skip": r = regen_satu(base, backlog, done)
        if r in (True, False): pass
        elif r is None:
            if not topik_baru(base, cad):
                log(f"{base}: aktif={n} IDLE, regen & cadangan habis -> andalkan NONTON")
    DONE.write_text(json.dumps(sorted(done), ensure_ascii=False), encoding="utf-8")
    CAD.write_text(json.dumps(cad, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
