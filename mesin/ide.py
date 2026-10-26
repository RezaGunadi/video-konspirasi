"""Bank ide topik + ide baru dari AI.

Tiap ide ditulis sebagai topik siap pakai untuk mode "AI tulis naskah". Topik yang tidak dimasukkan (dan ditolak
di generator AI): tragedi nyata yang korbannya masih dikenang keluarga, kesehatan/vaksin, pemilu, dan teori yang
menyerang kelompok agama/suku/ras. Topik semacam itu berisiko kena aturan YouTube dan menyakiti orang sungguhan.
"""
from . import ollama, riset

BANK = {
    "👽 UFO & Alien": [
        "Insiden Roswell 1947: balon cuaca rahasia atau piring terbang?",
        "Area 51: apa sebenarnya yang disembunyikan di pangkalan paling rahasia Amerika?",
        "Rendlesham Forest 1980: penampakan UFO di dekat pangkalan militer Inggris",
        "Phoenix Lights 1997: ribuan orang melihat cahaya raksasa di langit Arizona",
        "Sinyal Wow! 1977: pesan dari luar angkasa yang tidak pernah terulang",
        "Satelit Black Knight: benda asing yang katanya mengorbit bumi selama 13.000 tahun",
        "Oumuamua: batu antarbintang atau wahana alien?",
        "Wajah di Mars: patung raksasa atau tipuan cahaya?",
        "Video UFO Pentagon (Tic Tac, Gimbal, GoFast): apa kata Angkatan Laut AS?",
    ],
    "🚀 Luar Angkasa": [
        "Teori pendaratan Apollo 11 di bulan itu palsu dan direkam di studio",
        "Sisi gelap bulan: benarkah ada pangkalan rahasia di sana?",
        "Planet Nibiru: planet kiamat yang katanya akan menabrak bumi",
        "Kosmonot yang hilang: rumor astronot Soviet yang meninggal sebelum Yuri Gagarin",
        "Teori bulan berongga: benarkah bulan adalah pesawat raksasa?",
        "Program luar angkasa rahasia: benarkah ada armada di luar orbit bumi?",
    ],
    "🐉 Makhluk Legendaris": [
        "Monster Loch Ness: legenda Nessie, foto Surgeon 1934, dan penjelasan ilmiahnya",
        "Bigfoot: rekaman Patterson-Gimlin 1967 asli atau orang berkostum?",
        "Mothman: makhluk bersayap dan runtuhnya jembatan Silver Bridge",
        "Chupacabra: pengisap darah kambing dari Puerto Riko",
        "Yeti: jejak kaki raksasa di salju Himalaya",
        "Kraken: monster laut raksasa dari legenda pelaut Norwegia",
        "Megalodon: benarkah hiu purba raksasa masih hidup di laut dalam?",
        "Jersey Devil: makhluk bersayap dari hutan Pine Barrens",
        "Thunderbird: burung raksasa dalam legenda penduduk asli Amerika",
    ],
    "🌍 Bumi & Benua Rahasia": [
        "Teori bumi datar: Antartika dinding es raksasa dan benua lain di baliknya",
        "Teori bumi berongga dan kota Agartha di inti bumi",
        "Atlantis: benua yang tenggelam dalam satu hari menurut Plato",
        "Lemuria dan benua Mu: peradaban yang hilang di Samudra Pasifik",
        "Tartaria dan teori mud flood: kekaisaran yang katanya dihapus dari sejarah",
        "Peta Piri Reis 1513: benarkah menggambar Antartika sebelum ditemukan?",
        "Operasi Highjump 1946: ekspedisi Laksamana Byrd ke Antartika dan teori pangkalan rahasia",
        "Teori waktu hantu: benarkah tahun 614 sampai 911 tidak pernah ada?",
    ],
    "🏛️ Peradaban Kuno": [
        "Piramida Giza dibangun alien? Teori dan bukti arkeologinya",
        "Mekanisme Antikythera: komputer kuno berumur 2.000 tahun",
        "Baterai Baghdad: benarkah orang kuno sudah mengenal listrik?",
        "Garis Nazca: landasan pesawat alien atau gambar untuk para dewa?",
        "Manuskrip Voynich: buku yang tidak bisa dibaca siapa pun",
        "Sphinx dan teori erosi air: lebih tua dari yang kita kira?",
        "Göbekli Tepe: kuil 11.000 tahun yang mengubah sejarah",
        "Stonehenge: siapa yang membangun dan untuk apa?",
    ],
    "🕵️ Proyek Rahasia": [
        "Eksperimen Philadelphia 1943: kapal perang yang katanya menghilang",
        "Project Blue Beam: teori invasi alien palsu dengan hologram",
        "HAARP: antena raksasa Alaska yang dituduh bisa mengendalikan cuaca",
        "Proyek Montauk: eksperimen waktu dan pikiran yang katanya dirahasiakan",
        "Pangkalan Dulce: markas bawah tanah di New Mexico menurut teori konspirasi",
        "Penemuan Nikola Tesla yang hilang: listrik gratis dan sinar kematian",
    ],
    "✅ Konspirasi yang Ternyata Nyata": [
        "Proyek MKUltra: eksperimen pengendalian pikiran CIA yang terbukti nyata",
        "Operasi Northwoods: rencana militer AS yang ditolak Presiden Kennedy",
        "Operasi Mockingbird: dugaan CIA memengaruhi media",
        "Operasi Paperclip: ilmuwan Nazi yang direkrut Amerika",
        "COINTELPRO: program rahasia FBI memata-matai warganya sendiri",
        "Proyek Sunshine: pengumpulan sampel tulang untuk riset radiasi nuklir",
    ],
    "🎭 Tokoh & Sejarah": [
        "Elvis Presley masih hidup? Teori penampakan sang raja rock and roll",
        "Teori Paul McCartney sudah meninggal tahun 1966",
        "Hitler kabur ke Argentina: teori dan bukti sejarah tentang kematiannya",
        "Anastasia Romanov: putri Rusia yang katanya selamat dari eksekusi",
        "Shakespeare bukan penulis karyanya sendiri?",
        "Kematian misterius Napoleon: diracun atau sakit?",
    ],
    "🌊 Misteri Laut & Langit": [
        "Segitiga Bermuda: kapal dan pesawat yang menghilang tanpa jejak",
        "Suara Bloop 1997: monster laut atau gempa es?",
        "Kapal Mary Celeste 1872: kapal hantu tanpa awak",
        "Flight 19 tahun 1945: lima pesawat yang hilang di Segitiga Bermuda",
        "Insiden Celah Dyatlov 1959: misteri sembilan pendaki di Pegunungan Ural",
        "Hujan ikan dan katak dari langit: fenomena aneh yang benar-benar terjadi",
    ],
    "🔮 Kutukan & Mistis": [
        "Kutukan makam Tutankhamun: kematian misterius para penggali",
        "Berlian Hope: permata terkutuk yang membawa sial pemiliknya",
        "Boneka Annabelle: kisah nyata di balik film horor",
        "Robert the Doll: boneka terkutuk dari Key West",
        "Kotak Dybbuk: benda terkutuk yang dijual di internet",
    ],
    "💻 Teknologi & Realitas": [
        "Teori simulasi: benarkah kita hidup di dalam program komputer?",
        "Efek Mandela: kenapa banyak orang mengingat hal yang sama secara keliru",
        "Teori Internet Mati: benarkah sebagian besar internet diisi bot?",
        "John Titor: penjelajah waktu dari tahun 2036 yang muncul di forum internet",
        "Birds Aren't Real: teori konspirasi satire yang dipercaya sebagian orang",
    ],
    "🏝️ Misteri Nusantara": [
        "Gunung Padang: piramida tertua di dunia atau bukit alami?",
        "Teori Atlantis adalah Indonesia: Sundaland yang tenggelam setelah zaman es",
        "Orang Pendek: makhluk misterius di hutan Kerinci, Sumatra",
        "Ahool: kelelawar raksasa dari hutan Jawa",
        "Kota gaib Saranjana di Kalimantan Selatan",
        "Kota gaib Wentira di Sulawesi Tengah",
        "Legenda Candi Prambanan dibangun dalam satu malam: mitos dan sejarahnya",
        "Letusan Toba 74.000 tahun lalu: benarkah hampir memusnahkan manusia?",
        "Harta karun Bung Karno: mitos emas rahasia dan penipuan yang memanfaatkannya",
        "Legenda Nyi Roro Kidul dan larangan memakai baju hijau di pantai selatan",
    ],
}

PENJELASAN = {
    "👽 UFO & Alien": "penampakan UFO, alien, dan kontak luar angkasa dari seluruh dunia",
    "🚀 Luar Angkasa": "misi luar angkasa, bulan, planet, dan program antariksa",
    "🐉 Makhluk Legendaris": "kriptid dan makhluk legenda dari berbagai negara (bukan alien)",
    "🌍 Bumi & Benua Rahasia": "bentuk bumi, benua hilang/tersembunyi, Antartika, peta kuno, sejarah alternatif",
    "🏛️ Peradaban Kuno": "bangunan, artefak, dan naskah kuno yang misterius",
    "🕵️ Proyek Rahasia": "eksperimen dan proyek militer/pemerintah yang dirumorkan",
    "✅ Konspirasi yang Ternyata Nyata": "operasi rahasia yang SUDAH terbukti lewat dokumen resmi yang dibuka",
    "🎭 Tokoh & Sejarah": "tokoh sejarah yang sudah lama meninggal dan rumor tentang mereka",
    "🌊 Misteri Laut & Langit": "kapal/pesawat hilang, suara laut, fenomena alam aneh (bukan tragedi baru)",
    "🔮 Kutukan & Mistis": "benda terkutuk, kutukan makam, legenda horor terkenal",
    "💻 Teknologi & Realitas": "teori simulasi, efek Mandela, internet, penjelajah waktu",
    "🏝️ Misteri Nusantara": "legenda, mitos, makhluk, situs, dan misteri dari INDONESIA (Sumatra, Jawa, Bali, "
                            "Kalimantan, Sulawesi, Maluku, Papua, Nusa Tenggara); semuanya harus berlokasi di Indonesia",
}

SCHEMA = {"type": "object", "properties": {"ide": {
    "type": "array", "minItems": 10, "maxItems": 10,
    "items": {"type": "object", "properties": {"judul": {"type": "string"}, "wiki": {"type": "string"}},
              "required": ["judul", "wiki"]}}},
    "required": ["ide"]}


def buat_ide(cfg, kategori, hindari=(), batal=None):
    contoh = "\n".join(f"- {x}" for x in BANK.get(kategori, [])[:4])
    sudah = "\n".join(f"- {x}" for x in list(hindari)[:40])
    pesan = [{"role": "user", "content": (
        "Kamu perencana konten channel misteri & teori konspirasi berbahasa Indonesia.\n"
        f"KATEGORI: {kategori} = {PENJELASAN.get(kategori, kategori)}.\n"
        f"Contoh gaya topik:\n{contoh}\n\n"
        "Tulis 10 ide topik video BARU yang SEMUANYA termasuk kategori di atas (bukan yang sudah ada di daftar di "
        "bawah). Tiap ide: judul (bahasa Indonesia, spesifik dan menarik) dan wiki (nama topiknya persis seperti "
        "judul artikel Wikipedia, misalnya \"Orang Pendek\" atau \"Mothman\"). Hanya teori/legenda/misteri yang "
        "benar-benar ada dan punya artikel Wikipedia; jangan mengarang tempat, makhluk, atau teori baru. Hindari: "
        "tragedi nyata yang korbannya masih dikenang keluarga, kesehatan dan vaksin, pemilu, dan teori yang "
        "menyerang agama, suku, ras, atau kelompok tertentu.\n\n"
        f"SUDAH ADA:\n{sudah or '-'}")}]
    j = ollama.chat_json(cfg, pesan, SCHEMA, batal=batal, maks_token=900, suhu=0.9)
    lama = {x.lower() for x in hindari}
    calon = [x for x in j.get("ide", []) if isinstance(x, dict) and str(x.get("judul", "")).strip()
             and str(x["judul"]).strip().lower() not in lama]

    # Model kecil suka mengarang nama gua/kota/makhluk. Ide yang topiknya tidak ada di Wikipedia dibuang,
    # karena naskahnya nanti pasti ikut mengarang.
    def cek(x):
        return riset.ada_di_wikipedia(str(x.get("wiki") or x["judul"]))

    artikel = [cek(x) for x in calon]  # berurutan: Wikipedia membatasi permintaan beruntun
    lolos = [{"judul": str(x["judul"]).strip(" -•"), "wiki": a} for x, a in zip(calon, artikel) if a]
    return {"ide": lolos[:8], "dibuang": len(calon) - len(lolos)}
