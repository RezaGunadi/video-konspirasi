"""Video Konspirasi AI — server lokal (http://localhost:3220)."""
import ipaddress
import json
import os
import shutil
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from mesin import config, ide, ollama, proyek, render, suara, suara_mirip, suara_saya
from mesin.alat import DATA, FFMPEG, MUSIK, PROYEK, PUBLIC, INPUT, OUTPUT, slug

PORT = int(os.environ.get("PORT", 3220))
HOST_OK = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
# Mini PC (pekerja di LAN): UI & API boleh dibuka dari laptop lewat alamat jaringan lokal (192.168.x.x dsb.).
LAN = os.environ.get("VIDEO_AI_LAN") == "1"


def _host_boleh(host):
    if host in HOST_OK:
        return True
    if not LAN:
        return False
    try:
        return ipaddress.ip_address(host.rsplit(":", 1)[0]).is_private
    except ValueError:
        return False

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # video panjang untuk mode Re-create
# Urutan kunci dipertahankan: daftar suara diurutkan Flask secara alfabet sehingga "🎙️ Suara saya" terlempar ke
# paling bawah dan pengguna mengira pilihannya tidak ada.
app.json.sort_keys = False
SUMBER = DATA / "sumber"  # video sumber yang diupload untuk mode Re-create


@app.before_request
def jaga():
    # Hanya untuk laptop ini: tolak Host/Origin asing (mencegah situs lain memanggil API lewat browser).
    if not _host_boleh(request.host):
        abort(403)
    asal = request.headers.get("Origin")
    if asal and not _host_boleh(asal.split("://", 1)[-1]):
        abort(403)


@app.errorhandler(Exception)
def galat(e):
    kode = getattr(e, "code", 500)
    if kode == 500:
        app.logger.exception(e)
    return jsonify(ok=False, galat=str(getattr(e, "description", e))), kode


@app.get("/")
def beranda():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/aset/<path:nama>")
def aset(nama):
    return send_from_directory(PUBLIC, nama)


@app.get("/api/status")
def status():
    cfg = config.muat()
    models = ollama.daftar_model(cfg)
    return jsonify(ok=True, config=config.publik(), ollama=bool(models), models=models,
                   disclaimer_bawaan=config.DISCLAIMER_BAWAAN,
                   ffmpeg=Path(FFMPEG).exists() or FFMPEG == "ffmpeg", encoder=render.encoder(),
                   suara=({suara_saya.KODE: suara_saya.LABEL} if suara_saya.ada() else {}) | suara.SUARA,
                   musik=len([p for p in MUSIK.iterdir() if p.is_file()]),
                   suara_mirip=suara_mirip.tersedia(),
                   folder={"input": str(INPUT), "output": str(OUTPUT), "musik": str(MUSIK)})


@app.post("/api/config")
def simpan_config():
    data = request.get_json(force=True) or {}
    for k in ("pexels_key", "pixabay_key"):
        if k in data and ("…" in data[k] or data[k] == "•••"):
            data.pop(k)  # nilai tersamar dari GUI = tidak diubah
        elif k in data:
            data[k] = data[k].strip()
    if data.get("sumber_web") not in (None, "tidak", "berlisensi", "semua"):
        data.pop("sumber_web")
    config.simpan(data)
    return jsonify(ok=True, config=config.publik())


@app.get("/api/proyek")
def daftar():
    return jsonify(ok=True, proyek=proyek.daftar())


def _buat_dari_teks(teks, opsi, per_baris, nama=None):
    if per_baris:
        baris = [b.strip(" -•\t") for b in teks.splitlines() if b.strip(" -•\t")]
        return [proyek.buat(b, opsi) for b in baris]
    return [proyek.buat(teks, opsi, nama=nama)]


@app.post("/api/proyek")
def buat():
    data = request.get_json(force=True) or {}
    opsi = data.get("opsi") or {}
    config.simpan({"default": {k: opsi[k] for k in proyek.OPSI_KUNCI if k in opsi}})
    hasil = _buat_dari_teks(data.get("teks", ""), opsi, data.get("per_baris"))
    return jsonify(ok=True, id=[p["id"] for p in hasil])


@app.post("/api/recreate/upload")
def recreate_upload():
    """Simpan video panjang milik pengguna sebagai sumber mode Re-create."""
    f = request.files.get("file")
    if not f or not f.filename:
        abort(400, "Tidak ada file video")
    akhiran = Path(f.filename).suffix.lower()
    if akhiran not in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"):
        abort(400, "Format video tidak didukung (pakai mp4/mov/mkv/webm)")
    SUMBER.mkdir(parents=True, exist_ok=True)
    tujuan = SUMBER / (slug(Path(f.filename).stem, 60) + akhiran)
    f.save(tujuan)
    return jsonify(ok=True, path=str(tujuan), nama=Path(f.filename).stem)


@app.post("/api/recreate")
def recreate_buat():
    data = request.get_json(force=True) or {}
    sumber = data.get("sumber") or {}
    if sumber.get("jenis") == "file":
        path = Path(sumber.get("path") or "").resolve()
        if SUMBER.resolve() not in path.parents and INPUT.resolve() not in path.parents:
            abort(400, "File sumber harus diupload lewat aplikasi")  # jangan membaca file sembarang di disk
        sumber["path"] = str(path)
    rc = data.get("rc") or {}
    opsi = data.get("opsi") or {}
    opsi.update(durasi=int(rc.get("durasi") or 45), cta=str(rc.get("cta") or "").strip())
    try:
        hasil = proyek.buat_recreate(sumber, data.get("tema") or [], data.get("jumlah"), opsi, rc)
    except ValueError as e:
        abort(400, str(e))
    return jsonify(ok=True, id=[p["id"] for p in hasil])


@app.post("/api/proyek/upload")
def buat_dari_file():
    opsi = json.loads(request.form.get("opsi") or "{}")
    per_baris = request.form.get("per_baris") == "1"
    config.simpan({"default": {k: opsi[k] for k in proyek.OPSI_KUNCI if k in opsi}})
    ids = []
    for f in request.files.getlist("file"):
        mentah = f.read()
        try:
            teks = mentah.decode("utf-8-sig")
        except UnicodeDecodeError:
            teks = mentah.decode("cp1252", "replace")
        if teks.strip():
            ids += [p["id"] for p in _buat_dari_teks(teks, opsi, per_baris, nama=Path(f.filename or "").stem)]
    if not ids:
        abort(400, "File .txt kosong")
    return jsonify(ok=True, id=ids)


@app.get("/api/proyek/<pid>")
def detail(pid):
    p = proyek.detail(pid)
    if not p:
        abort(404, "Proyek tidak ditemukan")
    return jsonify(ok=True, proyek=p)


@app.post("/api/proyek/<pid>/<aksi>")
def aksi(pid, aksi):
    data = request.get_json(silent=True) or {}
    if aksi == "naskah":
        proyek.edit_naskah(pid, data.get("naskah", ""))
    elif aksi == "lanjut":
        proyek.lanjut(pid)
    elif aksi == "cari-ulang":
        proyek.cari_ulang_footage(pid)
    elif aksi == "tulis-ulang":
        proyek.tulis_ulang(pid, data.get("opsi"), data.get("teks"), data.get("sudut"))
    elif aksi == "link":
        try:
            proyek.atur_link(pid, data.get("link", ""))
        except ValueError as e:
            abort(400, str(e))
    elif aksi == "ulangi":
        proyek.ulangi(pid, data.get("opsi"))
    elif aksi == "pilih":
        proyek.pilih_footage(pid, int(data["adegan"]), int(data["shot"]), data.get("index"))
    elif aksi == "hapus-stiker":
        proyek.hapus_stiker(pid, int(data["adegan"]), int(data["shot"]))
    elif aksi == "upload-footage":
        f = request.files.get("file")
        if not f:
            abort(400, "Tidak ada file")
        folder = PROYEK / pid / "upload"
        folder.mkdir(parents=True, exist_ok=True)
        nama = slug(Path(f.filename or "footage").stem, 40) + Path(f.filename or ".mp4").suffix.lower()
        tujuan = folder / nama
        f.save(tujuan)
        proyek.pilih_footage(pid, int(request.form["adegan"]), int(request.form["shot"]), file_lokal=str(tujuan))
    elif aksi == "batal":
        proyek.batalkan(pid)
    elif aksi == "hapus":
        proyek.hapus(pid)
    elif aksi == "buka-folder":
        p = proyek.detail(pid) or {}
        folder = (p.get("hasil") or {}).get("folder")
        if folder and Path(folder).exists():
            _buka(folder)
    else:
        abort(404)
    return jsonify(ok=True)


@app.get("/hasil/<pid>/<jenis>")
def hasil(pid, jenis):
    p = proyek.detail(pid)
    if not p or not p.get("hasil"):
        abort(404)
    path = {"video": p["hasil"].get("video"), "thumbnail": p["hasil"].get("thumbnail"),
            "deskripsi": str(Path(p["hasil"]["folder"]) / "deskripsi.txt")}.get(jenis)
    if not path or not Path(path).exists():
        abort(404)
    return send_file(path, conditional=True, max_age=0)


@app.get("/api/ide")
def bank_ide():
    # Flask mengurutkan kunci JSON; urutan kategori dikirim terpisah.
    return jsonify(ok=True, ide=ide.BANK, urutan=list(ide.BANK))


@app.post("/api/ide")
def ide_ai():
    d = request.get_json(force=True) or {}
    kategori = d.get("kategori") if d.get("kategori") in ide.BANK else next(iter(ide.BANK))
    hindari = [*ide.BANK[kategori], *[str(x) for x in (d.get("hindari") or [])][:40]]
    return jsonify(ok=True, **ide.buat_ide(config.muat(), kategori, hindari))


@app.post("/api/contoh-suara")
def contoh_suara():
    d = request.get_json(force=True) or {}
    teks = (d.get("teks") or "").strip()[:300] or \
        "Tahun 1947, sesuatu jatuh di gurun dekat Roswell. Pemerintah bilang itu balon cuaca. Tapi benarkah begitu?"
    saya = d.get("suara") == suara_saya.KODE and suara_saya.ada()
    if saya:
        s = suara.bacakan(teks, suara_saya.suara_dasar(), int(d.get("kecepatan", -5)), suara_saya.nada_dasar())
        s = {**s, "mp3": suara_saya.ubah(s["mp3"])}
    else:
        s = suara.bacakan(teks, d.get("suara") if d.get("suara") in suara.SUARA else "id-ID-ArdiNeural",
                          int(d.get("kecepatan", -5)), int(d.get("nada", -6)))
    if d.get("suara_alami", True):  # contoh memakai waktu kata dari Edge (tanpa Whisper) supaya cepat
        wav, _ = suara.manusiawikan(s["mp3"], s["kata"], teks)
        return send_file(wav, mimetype="audio/wav", max_age=0)
    return send_file(s["mp3"], mimetype="audio/wav" if saya else "audio/mpeg", max_age=0)


@app.post("/api/buka/<nama>")
def buka_folder(nama):
    folder = {"input": INPUT, "output": OUTPUT, "musik": MUSIK}.get(nama)
    if not folder:
        abort(404)
    _buka(folder)
    return jsonify(ok=True)


def _buka(folder):
    """Buka folder di Explorer (Windows). Di mini PC Linux tanpa layar: tidak melakukan apa-apa."""
    if hasattr(os, "startfile"):
        os.startfile(folder)


if __name__ == "__main__":
    if not shutil.which(FFMPEG) and not Path(FFMPEG).exists():
        print(f"ffmpeg tidak ditemukan ({FFMPEG})", file=sys.stderr)
    proyek.mulai_pekerja()
    print(f"Video Konspirasi AI jalan di http://localhost:{PORT}" + (" (juga bisa dibuka dari LAN)" if LAN else ""))
    from waitress import serve
    serve(app, host="0.0.0.0" if LAN else "127.0.0.1", port=PORT, threads=8)
