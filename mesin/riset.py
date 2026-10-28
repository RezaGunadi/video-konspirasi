"""Bahan fakta dari Wikipedia supaya naskah tidak mengarang tanggal/nama/angka."""
import re
import time

import requests

from . import ollama
from .alat import http_get

SCHEMA_KATA = {
    "type": "object",
    "properties": {"en": {"type": "string"}, "id": {"type": "string"}},
    "required": ["en", "id"],
}


def kata_kunci(cfg, teks, batal=None):
    pesan = [{"role": "user", "content": (
        "Teks berikut adalah topik/bahan video tentang teori konspirasi atau misteri.\n"
        "Tulis judul artikel Wikipedia yang paling relevan: versi bahasa Inggris (en) dan bahasa Indonesia (id). "
        "Pilih artikel tentang LEGENDA, MITOS, TEORI KONSPIRASI, atau MISTERI-nya (bukan kondisi medis atau istilah "
        "umum yang namanya mirip). Cukup nama topiknya, misalnya {\"en\": \"Roswell incident\", \"id\": \"Insiden "
        "Roswell\"} atau {\"en\": \"Giant (mythology)\", \"id\": \"Raksasa\"}.\n\n"
        f"TEKS:\n{teks[:1500]}")}]
    try:
        return ollama.chat_json(cfg, pesan, SCHEMA_KATA, batal=batal, maks_token=60)
    except RuntimeError:
        return {"en": teks[:80], "id": teks[:80]}


def _artikel(lang, query, maks_huruf, tepat=False):
    """tepat=True: query sudah judul artikel yang pasti (dari tautan antarbahasa), tanpa pencarian."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    if tepat:
        judul = query
    else:
        r = http_get(api, params={"action": "query", "list": "search", "srsearch": query, "srlimit": 1,
                                  "format": "json"})
        hasil = (r.json().get("query", {}).get("search") or []) if r.ok else []
        if not hasil:
            return None
        judul = hasil[0]["title"]
    r = http_get(api, params={"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                              "titles": judul, "format": "json"})
    halaman = next(iter(r.json().get("query", {}).get("pages", {}).values()), {}) if r.ok else {}
    teks = halaman.get("extract") or ""
    # Buang bagian daftar pustaka dan sejenisnya.
    teks = re.split(r"\n==\s*(References|See also|External links|Referensi|Lihat pula|Pranala luar|Notes|Catatan)\s*==",
                    teks)[0]
    teks = re.sub(r"\n{3,}", "\n\n", teks).strip()
    if len(teks) < 200:
        return None
    return {"judul": judul, "lang": lang, "url": f"https://{lang}.wikipedia.org/wiki/{judul.replace(' ', '_')}",
            "teks": teks[:maks_huruf]}


def _artikel_tahan(lang, query, maks_huruf, log, batal=None, tepat=False):
    """_artikel yang menunggu jaringan pulih (1, 2, lalu 4 menit). DNS mini PC pernah mati ±3 menit: riset video hutan
    kosong dan naskahnya ditulis tanpa sumber, dengan hook mitos "kehabisan napas". Tetap gagal: RuntimeError."""
    for coba, jeda in enumerate((60, 120, 240, None)):
        try:
            return _artikel(lang, query, maks_huruf, tepat=tepat)
        except requests.RequestException as e:
            if jeda is None:
                raise RuntimeError(f"Wikipedia {lang} tidak bisa dihubungi setelah {coba + 1}x coba "
                                   f"({e.__class__.__name__}) — periksa internet mini PC lalu ulangi") from e
            log(f"Wikipedia {lang} gagal ({e.__class__.__name__}) — dicoba lagi {jeda} detik lagi")
            for _ in range(jeda):
                if batal:
                    batal.cek()
                time.sleep(1)


_UMUM = {"the", "of", "and", "in", "di", "dan", "yang", "dari", "ke", "misteri", "legenda", "teori", "mystery",
         "legend", "theory", "of", "a", "an"}


# Kolom terpisah: array berpanjang tetap membuat gemma mengulang token sampai dihentikan Ollama.
# Nama kolom harus jelas: "satu".."enam" di samping "kata_en" pernah membuat gemma menulis "enam_en:" sebagai judul.
_SLOT = tuple(f"judul_artikel_{i}" for i in range(1, 7))
SCHEMA_TERKAIT = {"type": "object", "properties": {**{k: {"type": "string"} for k in _SLOT},
                                                   "kata_kunci_inggris": {"type": "string"}},
                  "required": [*_SLOT, "kata_kunci_inggris"]}
# Nama cabang ilmu ("Geomorphology", "Paleontology") terlalu umum untuk jadi bahan cerita.
_ILMU_UMUM = re.compile(r"^\w+(ology|logy|graphy|nomy|ics)$", re.I)


def topik_terkait(cfg, teks, utama, batal=None, log=print):
    """Fakta nyata di sekitar topik yang bikin cerita lebih "mind blowing" — misalnya untuk konspirasi bulan:
    tempat latihan astronaut di Islandia, simulator pendaratan, sabuk radiasi Van Allen; untuk teori raksasa:
    patung kura-kura batu Bixi, gunung Sleeping Giant, petrifikasi. AI mengusulkan judul artikel; hanya yang
    benar-benar ada (judul hasil pencarian cocok) dan nyambung dengan topiknya yang dipakai."""
    pesan = [{"role": "user", "content": (
        f"Topik video misteri/konspirasi: {teks[:900]}\nArtikel Wikipedia utamanya: {utama}\n\n"
        "Sebutkan 6 judul artikel Wikipedia bahasa Inggris (selain artikel utama) tentang FAKTA NYATA yang "
        "berhubungan dan bisa membuat ceritanya lebih mengejutkan. Utamakan tiap benda, tempat, atau proses yang "
        "DISEBUT di topik/catatan di atas (bukti yang ingin dibahas, proses ilmiahnya) — pilih artikel yang "
        "SPESIFIK: nama benda, tempat, situs, atau peristiwa nyatanya, bukan nama cabang ilmu. Contoh: kura-kura "
        "batu raksasa → \"Bixi\"; gunung berbentuk orang berbaring → \"Sleeping Giant (Ontario)\"; manusia "
        "membatu → \"Petrifaction\" atau \"Cardiff Giant\"; piramida dibangun alien → \"Great Pyramid of Giza\"; peta bumi datar → \"Gleason's map\" atau "
        "\"Emblem of the United Nations\"; ekspedisi rahasia ke Antartika → \"Operation Highjump\"; "
        "tempat latihan astronaut → \"Apollo geology field training\". Kalau masih ada slot: tempat di Bumi yang "
        "mirip atau dipakai untuk simulasi, kondisi ilmiah yang sering dijadikan argumen, eksperimen penting, "
        "program atau dokumen rahasia yang sudah dibuka. Hanya judul artikel yang benar-benar ada.\n"
        "Isi juga kata_kunci_inggris: 8-12 kata kunci topik ini dalam bahasa Inggris, dipisah spasi "
        "(misalnya \"giant axe sword mountain salt blood cell turtle stone mineral\").")}]
    usul, kata_en = [], ""
    for coba in range(2):
        try:
            j = ollama.chat_json(cfg, pesan, SCHEMA_TERKAIT, batal=batal, maks_token=320, suhu=0.4 + coba * 0.3)
            usul = [str(j.get(k, "")).strip() for k in _SLOT if str(j.get(k, "")).strip()]
            usul = [t for t in usul if not re.search(r"_|:$", t)]  # sisa nama kolom, bukan judul
            kata_en = str(j.get("kata_kunci_inggris", ""))[:300]
            break
        except (RuntimeError, ValueError) as e:
            log(f"  Usulan topik terkait gagal ({e})")
    # Artikel terkait wajib menyinggung topik utamanya (mencegah "Dua Lipa" lolos untuk topik pendaratan bulan).
    # dicocokkan per awalan 5 huruf: "mineral" ~ "mineralisasi", "petrification" ~ "petrifaction". kata_en
    # menjembatani catatan berbahasa Indonesia dengan artikel berbahasa Inggris.
    kata_topik = {k[:5] for k in re.findall(r"\w+", f"{utama} {kata_en} {teks[:900]}".lower())
                  if k not in _UMUM and len(k) > 3}
    return _verifikasi(usul, kata_topik, utama, [], 2500, log), kata_topik


def _verifikasi(usul, kata_topik, utama, sudah, maks_huruf, log, label="terkait"):
    """Artikel usulan AI dipakai hanya kalau benar-benar ada (judul hasil pencarian cocok) dan isinya menyinggung
    topik video (minimal 2 kata topik)."""
    hasil, ada = [], {utama.lower(), *(j.lower() for j in sudah)}
    for t in usul:
        t = str(t).strip()
        kata = {k[:5] for k in re.findall(r"\w+", t.lower()) if k not in _UMUM and len(k) > 2}
        if not kata or _ILMU_UMUM.match(t):
            continue
        try:
            a = _artikel("en", t, maks_huruf)
        except Exception:
            a = None
        if not a or a["judul"].lower() in ada:
            continue
        judul = {k[:5] for k in re.findall(r"\w+", a["judul"].lower())}
        isi = {k[:5] for k in re.findall(r"\w+", a["teks"].lower())}
        cocok = len(kata & judul) >= max(1, (len(kata) + 1) // 2)
        nyambung = len(kata_topik & isi) >= 2
        if cocok and nyambung:
            hasil.append({**a, "terkait": True})
            ada.add(a["judul"].lower())
            log(f"  ✓ {label}: {a['url']}")
        else:
            log(f"  ✗ “{t}” tidak dipakai (hasil pencarian: {a['judul']}, "
                f"{'judul tidak cocok' if not cocok else 'kurang nyambung dengan topik'})")
    return hasil


_FRASA = tuple(f"frasa_pencarian_{i}" for i in range(1, 9))
SCHEMA_GALI = {"type": "object", "properties": {k: {"type": "string"} for k in _FRASA}, "required": list(_FRASA)}
# Artikel budaya pop (game, film, tokoh fiksi) bukan bahan bukti.
_POP = re.compile(r"\b(video game|film|television series|TV series|sitcom|album|song|band|novel|comic|fictional|"
                  r"character|episode|wrestler|footballer|screenwriter|actor|actress|singer|rapper|role-playing|"
                  r"game|Dungeons)\b", re.I)
_UMUM_SUBJEK = {"theor", "consp", "myste", "legen", "myth", "mytho", "hoax"}


def _kalimat_subjek(teks, subjek, maks=2):
    """Kalimat yang menyebut subjek utama (misalnya "giant"), untuk dinilai AI."""
    hasil = []
    for k in re.split(r"(?<=[.!?])\s+", teks):
        if {w[:5] for w in re.findall(r"\w+", k.lower())} & subjek:
            hasil.append(k.strip()[:220])
            if len(hasil) >= maks:
                break
    return hasil


def gali_bukti(cfg, teks, utama, kata_topik, sudah, batal=None, log=print):
    """Dua putaran supaya galiannya dalam: putaran kedua tahu bukti yang sudah ketemu dan mencari yang lain."""
    hasil = []
    for putaran in range(2):
        baru = _gali_putaran(cfg, teks, utama, kata_topik, [*sudah, *(h["judul"] for h in hasil)], batal, log)
        hasil += baru
        if len(hasil) >= 8 or not baru:
            break
    return hasil[:10]


def _gali_putaran(cfg, teks, utama, kata_topik, sudah, batal=None, log=print):
    """Bukti/klaim LAIN yang biasa diajukan penganut teori, di luar yang ditulis pengguna. Model 12B sering tidak
    hafal judul artikelnya (mengusulkan "Atlantis" untuk teori raksasa), jadi AI cukup menulis FRASA pencarian
    tentang klaim yang beredar, pencarian Wikipedia menemukan artikelnya ("red haired giants cave Nevada" →
    Lovelock Cave, Si-Te-Cah), lalu AI menilai sekaligus mana yang benar-benar bukti/legenda untuk teori ini
    (hitungan kata saja meloloskan taman nasional yang kebetulan menyebut "giant clam")."""
    pesan = [{"role": "user", "content": (
        f"Topik video teori konspirasi/misteri: {teks[:900]}\nSubjek utama: {utama}\n"
        f"Bukti yang sudah dibahas: {', '.join(sudah) or '-'}\n\n"
        "Penganut teori ini biasanya mengajukan bukti, temuan, laporan, situs, benda, catatan sejarah, atau legenda "
        "apa saja? Gali sebanyak mungkin, termasuk klaim viral di internet dan temuan yang belakangan terbukti "
        "hoaks. Tulis 8 FRASA PENCARIAN bahasa Inggris (3-6 kata), satu frasa untuk tiap bukti yang BERBEDA, selain "
        "bukti yang sudah dibahas. Contoh pola untuk teori raksasa: \"giant human skeletons discovered\", "
        "\"red haired giants cave Nevada\", \"giant footprint in rock\"; untuk teori peradaban kuno maju: "
        "\"ancient battery Baghdad\", \"ancient Greek mechanical computer\".")}]
    frasa = []
    for coba in range(2):
        try:
            j = ollama.chat_json(cfg, pesan, SCHEMA_GALI, batal=batal, maks_token=260, suhu=0.6 + coba * 0.2)
            frasa = list(dict.fromkeys(" ".join(str(j.get(k) or "").split())[:80] for k in _FRASA))
            frasa = [f for f in frasa if f and not re.search(r"_|:$", f)]
            break
        except (RuntimeError, ValueError) as e:
            log(f"  Gali bukti lain gagal ({e})")
    subjek = {k[:5] for k in re.findall(r"\w+", re.sub(r"\(.*?\)", "", utama).lower()) if len(k) > 3} - _UMUM_SUBJEK
    # 1) kumpulkan calon artikel dari pencarian Wikipedia
    calon, ada = [], {utama.lower(), *(x.lower() for x in sudah)}
    api = "https://en.wikipedia.org/w/api.php"
    for f in frasa:
        try:
            r = http_get(api, params={"action": "query", "list": "search", "srsearch": f, "srlimit": 3, "format": "json"})
            judul_cari = [h["title"] for h in (r.json().get("query", {}).get("search") or [])] if r.ok else []
        except Exception:
            continue
        for judul in judul_cari:
            if judul.lower() in ada or _ILMU_UMUM.match(judul) or _POP.search(judul) or judul.startswith("List of"):
                continue
            ada.add(judul.lower())
            try:
                a = _artikel("en", judul, 2000, tepat=True)
            except Exception:
                a = None
            if not a or _POP.search(a["teks"][:300]):
                continue
            kalimat = _kalimat_subjek(a["teks"], subjek)
            if kalimat and len(kata_topik & {k[:5] for k in re.findall(r"\w+", a["teks"].lower())}) >= 2:
                calon.append((f, a, kalimat))
    if not calon:
        return []
    # 2) AI menilai semua calon sekaligus
    kolom = [f"relevan_{i}" for i in range(1, len(calon) + 1)]
    daftar = "\n\n".join(f"{i + 1}. {a['judul']}: {a['teks'][:280]} … {' … '.join(k)}"
                         for i, (_, a, k) in enumerate(calon))
    pesan = [{"role": "user", "content": (
        f"Topik video: {teks[:400]}\nSubjek utama: {utama}\n\nARTIKEL CALON:\n{daftar}\n\n"
        f"Untuk tiap artikel, isi relevan_N = true HANYA kalau artikel itu membahas {utama} SEBAGAI SUBJEKNYA: "
        f"kesaksian, temuan, kerangka/fosil, situs, catatan sejarah, atau legenda tentang {utama} itu sendiri "
        "(termasuk klaim yang terbukti hoaks). Isi false kalau kata itu hanya dipakai sebagai kata sifat \"besar\" "
        "(patung raksasa, hewan raksasa, senjata atau mesin raksasa), tentang fiksi/game, atau tidak berhubungan.")}]
    try:
        nilai = ollama.chat_json(cfg, pesan, {"type": "object", "properties": {k: {"type": "boolean"} for k in kolom},
                                              "required": kolom}, batal=batal, maks_token=12 * len(kolom) + 60, suhu=0.1)
    except (RuntimeError, ValueError) as e:
        log(f"  Penilaian bukti lain gagal ({e}) — tidak ada yang ditambahkan")
        return []
    hasil = []
    for k, (f, a, _) in zip(kolom, calon):
        if nilai.get(k) is True and len(hasil) < 8:
            hasil.append({**a, "terkait": True})
            log(f"  ✓ bukti lain (“{f}”): {a['url']}")
        else:
            log(f"  ✗ “{a['judul']}” bukan bukti untuk topik ini")
    return hasil


def _tautan_bahasa(judul_en, lang):
    """Judul artikel yang sama di Wikipedia bahasa lain (langlinks), atau None."""
    try:
        r = http_get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "langlinks", "lllang": lang, "redirects": 1, "titles": judul_en,
            "format": "json"})
        halaman = next(iter(r.json().get("query", {}).get("pages", {}).values()), {}) if r.ok else {}
    except Exception:
        return None
    ll = halaman.get("langlinks") or []
    return ll[0].get("*") if ll else None


_cek_cache = {}


def ada_di_wikipedia(kata_kunci):
    """Judul artikel Wikipedia (id/en) yang cocok dengan kata kunci, atau None. Dipakai untuk menyaring ide fiktif."""
    kunci = kata_kunci.strip().lower()
    if kunci not in _cek_cache:
        _cek_cache[kunci] = _cari_artikel(kata_kunci)
    return _cek_cache[kunci]


def _cari_artikel(kata_kunci):
    kata = {k for k in re.findall(r"\w+", kata_kunci.lower()) if k not in _UMUM and len(k) > 2}
    if not kata:
        return None
    for lang in ("id", "en"):
        try:
            r = http_get(f"https://{lang}.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": kata_kunci, "srlimit": 3, "format": "json"})
            hasil = r.json().get("query", {}).get("search", []) if r.ok else []
        except Exception:
            continue
        for h in hasil:
            judul = set(re.findall(r"\w+", h["title"].lower()))
            if len(kata & judul) >= max(1, (len(kata) + 1) // 2) and _bertema(lang, h["title"]):
                return f"{lang}:{h['title']}"
    return None


TEMA = re.compile(r"mitos|mitologi|legenda|cerita rakyat|dongeng|misteri|misterius|gaib|kriptid|hantu|takhayul|"
                  r"kutukan|konspirasi|teori|rahasia|kuno|purba|prasejarah|arkeolog|artefak|penampakan|"
                  r"myth|legend|folklore|cryptid|myster|conspirac|theor|hoax|paranormal|supernatural|\bUFO|"
                  r"alleged|purported|pseudo|hypothes|covert|secret|classified|ancient|prehistoric|archaeolog|"
                  r"artifact|curse|haunt|sighting|unexplained|disappear", re.I)


def _bertema(lang, judul):
    """Paragraf pembuka artikel harus menyinggung legenda/misteri/teori/arsip, bukan sekadar nama tempat/maskapai."""
    try:
        r = http_get(f"https://{lang}.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
            "titles": judul, "format": "json"})
        halaman = next(iter(r.json().get("query", {}).get("pages", {}).values()), {}) if r.ok else {}
    except Exception:
        return False
    return bool(TEMA.search(halaman.get("extract") or ""))


def kumpulkan(cfg, teks, batal=None, log=print, panjang=False, gali=False):
    """panjang=True (video > 3 menit): ambil lebih banyak isi artikel."""
    kk = kata_kunci(cfg, teks, batal)
    log(f"Riset Wikipedia: “{kk.get('en')}” / “{kk.get('id')}”")
    sumber = []
    batas = (14000, 5000) if panjang else (6000, 3000)
    try:
        en = _artikel_tahan("en", kk["en"], batas[0], log, batal) if kk.get("en") else None
    except RuntimeError:  # jaringan tetap mati: proyek berhenti, jangan menulis tanpa sumber
        raise
    except Exception as e:
        log(f"Wikipedia en gagal: {e}")
        en = None
    if en:
        sumber.append(en)
        log(f"  ✓ {en['url']}")
    # Artikel Indonesia: utamakan tautan antarbahasa dari artikel Inggrisnya (topik yang sama persis). Hasil
    # pencarian bebas bisa meleset jauh — "Raksasa" pernah memberi "Padma raksasa" (bunga Rafflesia).
    id_judul = _tautan_bahasa(en["judul"], "id") if en else None
    try:
        if id_judul:
            a = _artikel_tahan("id", id_judul, batas[1], log, batal, tepat=True)
        elif kk.get("id"):
            a = _artikel_tahan("id", kk["id"], batas[1], log, batal)
            if a and not _bertema("id", a["judul"]):
                log(f"  ✗ Wikipedia id “{a['judul']}” tidak sesuai topik, dilewati")
                a = None
        else:
            a = None
    except RuntimeError:
        raise
    except Exception as e:
        log(f"Wikipedia id gagal: {e}")
        a = None
    if a and a["judul"] not in {s_["judul"] for s_ in sumber}:
        sumber.append(a)
        log(f"  ✓ {a['url']}")
    if sumber:  # fakta nyata di sekitar topik untuk bahan cerita yang lebih seru
        terkait, kata_topik = topik_terkait(cfg, teks, sumber[0]["judul"], batal, log)
        sumber += terkait
        if gali:  # gaya "bangun teori": cari juga bukti/klaim lain di luar catatan pengguna
            log("Menggali bukti & klaim lain dari penganut teori ini…")
            sumber += gali_bukti(cfg, teks, sumber[0]["judul"], kata_topik, [x["judul"] for x in sumber], batal, log)
    return sumber
