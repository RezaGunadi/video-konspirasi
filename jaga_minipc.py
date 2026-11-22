# -*- coding: utf-8 -*-
"""Jaga mini PC A/B/C biar TIDAK NGANGGUR. Tiap mini PC yg proyek aktif (jalan+antri) < AMBANG
diisi topik baru dari rahasia/topik_cadangan.json (diambil & dihapus dari cadangan). Idempoten & aman.
Dipanggil berkala (Task Scheduler "JagaMiniPC", tiap 2 jam). Log ke rahasia/jaga_minipc.log.
Prioritas user: regen > generate baru > nonton (lihat memory minipc-jangan-nganggur).
NONTON = baseline OS/browser (auto-play) — di luar skrip ini.
  .venv\\Scripts\\python.exe jaga_minipc.py            # top-up kalau idle
  .venv\\Scripts\\python.exe jaga_minipc.py --status    # cek saja, tak antre
"""
import sys, json, argparse, time
from pathlib import Path
from datetime import datetime
import requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent; RAH = ROOT / "rahasia"
CAD = RAH / "topik_cadangan.json"; LOG = RAH / "jaga_minipc.log"
PC = ["http://192.168.100.63:3220", "http://192.168.100.54:3220", "http://192.168.100.71:3220"]
AMBANG = 2          # kalau aktif < 2 -> isi
ISI = 6             # jumlah topik yg diantre per top-up
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
    s = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} {t}"
    print(s, flush=True)
    try: LOG.open("a", encoding="utf-8").write(s + "\n")
    except Exception: pass

def aktif(base):
    pr = requests.get(base + "/api/proyek", timeout=8).json().get("proyek", [])
    return sum(1 for p in pr if (p.get("status") or "") not in TERM)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    cad = json.loads(CAD.read_text(encoding="utf-8")) if CAD.exists() else []
    for base in PC:
        try: n = aktif(base)
        except Exception as e: log(f"{base}: TAK TERHUBUNG ({str(e)[:40]})"); continue
        if a.status: log(f"{base}: aktif={n}"); continue
        if n >= AMBANG: log(f"{base}: aktif={n} (cukup, skip)"); continue
        if not cad: log(f"{base}: aktif={n} IDLE tapi CADANGAN TOPIK HABIS — perlu diisi (sementara andalkan nonton)"); continue
        ambil = cad[:ISI]; sisa = cad[ISI:]
        try:
            r = requests.post(base + "/api/proyek", json={"teks": "\n".join(ambil), "opsi": OPSI, "per_baris": True}, timeout=30)
            ids = r.json().get("id", [])
            cad = sisa; CAD.write_text(json.dumps(cad, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"{base}: aktif={n} -> antre {len(ids)} topik baru (cadangan sisa {len(cad)})")
        except Exception as e:
            log(f"{base}: GAGAL antre ({str(e)[:50]})")
    if not a.status and len(cad) < ISI:
        log(f"PERINGATAN: cadangan topik tinggal {len(cad)} — isi ulang rahasia/topik_cadangan.json")

if __name__ == "__main__":
    main()
