"""Menulis naskah, judul/deskripsi, dan memecah naskah jadi adegan + kata kunci footage."""
import difflib
import json
import re

from . import ollama

KATA_PER_DETIK = 2.2  # suara Ardi/Gadis di kecepatan -5%

_PERAN = """Kamu penulis naskah voice-over untuk channel YouTube/TikTok berbahasa Indonesia tentang misteri, legenda, dan teori konspirasi.
Topiknya bisa apa saja: UFO, misi luar angkasa, makhluk legendaris/kriptid (Bigfoot, Nessie, Mothman, Kraken), bumi datar, benua tersembunyi di balik Antartika, peradaban hilang, dan sebagainya."""

_ATURAN_UMUM = """- Bahasa Indonesia lisan yang enak didengar, menyapa penonton dengan "kamu". Kalimat pendek, 6 sampai 18 kata.
- Nama, tanggal, angka, dan kutipan HANYA boleh diambil dari BAHAN FAKTA atau dari pengetahuan yang sangat umum. Jangan mengarang kutipan, dokumen, saksi, atau angka. Kalau ragu, ceritakan tanpa detail angka.
- Fakta yang terdokumentasi boleh disampaikan sebagai fakta. Isi teori SELALU diberi penanda klaim seperti "banyak yang yakin", "banyak yang tidak percaya", "banyak orang curiga", "ada yang menduga", "bagaimana kalau", "mungkin saja". JANGAN menulis "para penganut teori (konspirasi)", "pendukung/pengikut/pengamat teori", atau "penganutnya" — tulis seperti orang ngobrol, misalnya "Banyak yang tidak percaya pendaratan itu nyata." Jangan pernah menyatakan teori sebagai fakta yang sudah terbongkar.
- Jangan menyerang suku, agama, ras, atau kelompok. Jangan menuduh orang nyata berbuat kejahatan tanpa bukti. Untuk topik kesehatan, jangan mendorong orang menolak pengobatan atau vaksin.
CARA MEMBANGUN NARASI SUPAYA LEGIT (berlaku untuk tema apa pun):
- Bangun dari hal yang bisa dicek penonton: foto atau rekaman terkenal, nama tempat, tahun, dokumen, atau tokoh nyata dari BAHAN FAKTA. Sebut dulu faktanya dengan tenang, baru masukkan kecurigaannya.
- Tiap klaim ditempelkan ke detail spesifik (nama, tempat, tahun, angka, ukuran). Jangan menulis klaim mengambang seperti "banyak bukti aneh" atau "kemiripannya sangat mencolok" tanpa menyebut buktinya atau apa yang mirip.
- Bedakan dengan jelas: fakta ditulis sebagai kalimat biasa ("Foto ini diambil tahun 1969."), kecurigaan ditulis sebagai suara orang banyak ("Tapi banyak yang tidak percaya foto ini asli.").
- Tunjukkan, jangan cuma bilang: ganti kata seperti "sangat misterius", "mencurigakan", "mengerikan" dengan detail yang membuat penonton merasakannya sendiri.
- Hindari kalimat klise khas AI: "mari kita selami", "misteri yang belum terpecahkan hingga kini", "tak lekang oleh waktu", "dunia penuh misteri", "fakta mengejutkan", "bikin bulu kuduk merinding".
- Narasi mengalir sebagai satu cerita: tiap paragraf menjawab satu pertanyaan dan memancing pertanyaan berikutnya.
SUPAYA ENAK DIUCAPKAN (suara narator harus terdengar seperti orang bercerita, bukan membacakan teks):
- Variasikan panjang kalimat. Sesekali kalimat sangat pendek (2-4 kata) untuk penekanan, misalnya "Bukan kiasan." atau "Ternyata bukan."
- Pakai pertanyaan retoris dan sesekali kata lisan seperti "nah", "coba bayangkan", "ternyata", "kan" — paling banyak satu per paragraf, jangan dipaksakan.
- Hindari kata baku yang kaku saat diucapkan: "merupakan", "tersebut", "yakni", "adapun", "oleh karena itu", "dikarenakan", "hal ini". Ganti dengan "adalah/itu/ini/karena".
- Tanpa singkatan dan tanpa tanda kurung. Tanda "…" boleh untuk jeda dramatis, paling banyak dua kali per paragraf.
- Keluarkan HANYA teks narasi polos: tanpa judul, tanpa label seperti "Hook:" atau "Narator:", tanpa emoji, tanpa markdown, tanpa petunjuk visual dalam kurung. Pisahkan paragraf dengan baris kosong."""

GAYA_NASKAH = {
    # Channel berita sains/penemuan (contoh pengguna: channel SISITERANG): fakta mengejutkan → kenapa itu aneh →
    # pertanyaan dijawab satu per satu dengan analogi dan pembanding skala → rangkuman → dampak. Tanpa opini/konspirasi.
    "sains": {
        "gaya": ("Gayamu seperti narator channel sains populer Indonesia: tenang, jelas, penuh rasa takjub. Kamu mengubah "
                 "temuan ilmiah jadi teka-teki yang dijawab satu per satu dengan bahasa yang gampang dipahami orang awam."),
        "aturan": """- Ikuti arahan dari TOPIK / CATATAN pembuat video, tetap dengan aturan di bawah.
- Ini video FAKTA, bukan teori konspirasi atau opini. Semua isi harus benar menurut BAHAN FAKTA atau pengetahuan ilmiah yang sangat umum. Bedakan yang sudah pasti ("para ilmuwan menemukan", "hasil pengukuran menunjukkan") dari dugaan ilmiah ("para ilmuwan menduga", "kemungkinan besar"). Kalau ragu, jangan sebut angka.
- HOOK = dua kalimat pertama, masing-masing maksimal 14 kata: fakta paling mengejutkan dari topik ini yang bisa langsung dibayangkan, lalu kontras "tapi…" yang memancing pertanyaan besar. Polanya seperti "Organisme terbesar di dunia bukan paus biru. Tapi sebuah hutan yang semua pohonnya berbagi satu akar." — tulis kalimatmu sendiri dari topik ini, jangan menyalin contoh. JANGAN membuka dengan pengantar, definisi, sapaan, "tahukah kamu", "jika kamu berdiri di…", atau latar sejarah.
- Kalimat ketiga: janji yang baru terjawab di akhir video, dengan kata-katamu sendiri (polanya seperti "Dan alasannya mengubah cara kita memandang hutan.").
- Lalu jelaskan kenapa itu aneh: bagaimana biasanya, lalu apa yang berbeda di sini ("Sungai besar biasanya berkelok dan berpindah. Tapi Nil tidak.").
- Susun sebagai rangkaian pertanyaan yang dijawab satu per satu. Tiap jawaban membuka pertanyaan berikutnya, dan tiap paragraf diakhiri pancingan ke paragraf berikutnya ("Tapi itu belum yang paling aneh.", "Lalu dari mana tekanan sebesar itu?"). Urutkan dari yang mengejutkan ke yang PALING mengejutkan; jawaban hook disimpan untuk menjelang akhir.
- Untuk konsep yang sulit, pakai analogi sehari-hari ("bayangkan selang taman yang dibiarkan menyala", "cara kerjanya mirip lampu lava raksasa") dan pembanding skala yang mudah dibayangkan ("seluas 32 ribu kolam renang olimpiade").
- Angka dan pembanding dari BAHAN FAKTA dipakai PERSIS dengan acuannya. Jangan menggabungkan angka atau satuan dari dua kalimat berbeda, jangan menambah acuan yang tidak ditulis sumbernya ("di setiap inci persegi", "di atas tubuhmu"), dan jangan membesar-besarkan angka ("ribuan ton" padahal sumbernya 8 ton). Kalau sumber tidak menyebut pembanding itu berlaku untuk luas atau benda apa, sebut saja "setara dengan berat …". Pertahankan juga keterangan waktunya: angka yang menurut sumber berlaku dulu atau di awal ("mulai bergerak … per tahun", "pada zaman es") jangan ditulis seolah terjadi sekarang.
- Perbandingan dengan benda sehari-hari yang angkanya TIDAK ada di BAHAN FAKTA ("lebih cepat dari tumbuhnya kuku", "setinggi gedung 30 lantai") hanya boleh kalau kamu sudah menghitung keduanya dalam satuan yang sama dan arahnya benar. Kalau ragu, sebut angkanya saja tanpa pembanding.
- PADAT: setiap fakta, angka, dan perbandingan disebut SATU KALI saja di seluruh naskah. JANGAN merangkum ulang isi yang sudah disebut, jangan "Pertama… Kedua… Ketiga…" yang mengulang penjelasan sebelumnya. Buang kalimat yang tidak menambah informasi baru atau ketegangan, termasuk transisi kosong seperti "Namun, untuk memahami…", "Lantas, bagaimana…", "Hal ini membuktikan bahwa…". Kata "luar biasa", "Namun", dan "Sebagai perbandingan" masing-masing paling banyak satu kali.
- Sebut angka konkret (tahun, ukuran, jarak, umur) dengan satuan yang biasa dipakai di Indonesia (meter, kilometer, derajat Celsius).
- Penutup: jawab pertanyaan dari hook dengan satu atau dua kalimat yang bikin "wow" (boleh sedikit jenaka), lalu satu pertanyaan ke penonton.""",
        "pendek": ("Alur: hook dua kalimat (fakta paling mengejutkan + kontras \"tapi…\"), janji, kenapa itu aneh, "
                   "jawaban para ilmuwan dengan satu analogi dan satu angka pembanding, jawaban hook yang bikin wow, "
                   "pertanyaan penutup. Tanpa rangkuman."),
        "panjang": ("Alur: hook dua kalimat (fakta paling mengejutkan + kontras \"tapi…\"), janji, kenapa itu aneh, "
                    "rangkaian pertanyaan yang dijawab satu per satu dengan ketegangan yang terus naik (tiap jawaban "
                    "membuka pertanyaan berikutnya), fakta paling mengejutkan menjelang akhir, jawaban hook yang bikin "
                    "wow, pertanyaan penutup. Tanpa rangkuman yang mengulang."),
    },
    # Host yang ngobrol ke kamera dan "menyambungkan titik" dari fakta yang tercatat (contoh pengguna: video krisis
    # air Bill Gates). Yang membuatnya meyakinkan adalah fakta nyata yang spesifik + pertanyaan retoris, bukan klaim
    # karangan: kesimpulan konspirasinya selalu berupa pertanyaan atau kecurigaan.
    "meyakinkan": {
        "gaya": ("Gayamu seperti host channel YouTube yang membongkar sesuatu sambil ngobrol langsung ke kamera: santai, "
                 "yakin, sedikit ngegas, bicara sebagai \"aku\" ke \"kamu\". Kamu bukan narator dokumenter — kamu sedang "
                 "menunjukkan ke temanmu hal-hal yang menurutmu tidak beres, satu per satu, sampai dia ikut curiga."),
        "aturan": """- Ikuti arahan dari TOPIK / CATATAN pembuat video (sudut pandang, hal yang harus dibahas), tetap dengan aturan di bawah.
- Buka (maksimal tiga kalimat) dengan hal yang pasti pernah didengar penonton, langsung sebut teorinya dengan jelas, lalu janjikan buktinya. Misalnya: "Kamu pasti pernah dengar soal Area 51. Banyak yang yakin, di sana Amerika menyembunyikan pesawat yang jauh lebih canggih dari yang mereka akui. Dan yang mau aku tunjukin bukan gosip, ini hal yang tercatat."
- Sekali di awal, jawab dulu skeptisnya penonton: "Mungkin kamu langsung mikir, ah, teori konspirasi lagi. Oke. Tapi lihat dulu datanya."
- Bangun REKAM JEJAK: fakta nyata dari BAHAN FAKTA disusun berurutan dengan tahun, nama, tempat, angka, dan ucapan yang memang tercatat di BAHAN FAKTA. Fakta nyata adalah senjata utamamu: makin spesifik, makin meyakinkan. Pakai kata penunjuk seperti "Lihat ini.", "Perhatiin detailnya.", "Coba lihat tahunnya."
- SAMBUNGKAN TITIK: taruh dua fakta nyata berdampingan, lalu biarkan penonton menarik kesimpulan lewat pertanyaan retoris. Misalnya "Tahun sekian mereka bilang A. Beberapa tahun kemudian, B benar-benar terjadi. Kebetulan?" Kesimpulan konspirasinya SELALU berupa pertanyaan atau kecurigaan pribadi ("aku curiga…", "kok bisa pas begitu?", "coba pikir"), BUKAN pernyataan fakta.
- Kalau relevan, tanyakan siapa yang diuntungkan dan kenapa baru sekarang, tapi jangan menuduh orang nyata melakukan kejahatan.
- Selipkan kalimat pendek yang menghentak, misalnya "Bukan aku yang bilang.", "Itu tercatat.", "Coba pikir."
- Paling banyak tiga kali di seluruh naskah boleh frasa Inggris pendek yang biasa dipakai anak muda Indonesia, misalnya "think about it" atau "plot twist".
- Menjelang akhir: sebut versi resmi dalam satu atau dua kalimat secara adil tanpa mengejek, lalu sikap pribadi yang rendah hati tapi tetap curiga, misalnya "Ini kacamata aku. Bisa jadi aku salah, dan jujur aku berharap aku salah. Tapi semua yang aku tunjukin tadi itu tercatat."
- Tutup dengan satu pertanyaan ke penonton supaya berkomentar.""",
        "pendek": ("Alur: hook hal yang pernah didengar + teorinya disebut jelas, jawab skeptis penonton, dua atau tiga "
                   "fakta nyata yang masing-masing dijelaskan artinya, pertanyaan \"kebetulan?\", kesimpulan yang "
                   "menjawab pertanyaan besar menurut teori, versi resmi singkat, sikap pribadi \"bisa jadi aku "
                   "salah\", pertanyaan penutup."),
        "panjang": ("Alur: hook hal yang pernah didengar + teorinya disebut jelas, jawab skeptis penonton, rekam jejak "
                    "berurutan dari fakta-fakta nyata (tiap fakta dijelaskan artinya), titik-titik yang disambungkan "
                    "satu per satu dengan ketegangan yang terus naik (tiap sambungan diakhiri pertanyaan retoris), pola "
                    "besarnya dan siapa yang diuntungkan, kenapa ini penting buat penonton, kesimpulan yang menjawab "
                    "pertanyaan besar menurut teori, versi resmi singkat secara adil, sikap pribadi \"bisa jadi aku "
                    "salah\", pertanyaan penutup."),
    },
    # Seru seperti penyelidikan: fakta nyata mengejutkan → kecurigaan dibangun → twist → satu kalimat fakta.
    "twist": {
        "gaya": "Gayamu seperti narator dokumenter misteri yang sedang membongkar kasus: dramatis, penuh rasa penasaran, bikin penonton merinding dan tidak mau berhenti menonton.",
        "aturan": """- Ikuti arahan cerita dari TOPIK / CATATAN pembuat video (sudut pandang, hal yang harus dibahas, twist yang diinginkan), tetap dengan aturan di bawah.
- KONSPIRASINYA DULU yang ditonjolkan, bukan penjelasan resminya. Kalimat pertama (maksimal 15 kata) langsung melempar kecurigaan terbesar sebagai klaim, misalnya "Lihat foto ini baik-baik. Banyak orang yakin, ini bukan di Bulan." Klaim tetap diberi penanda (banyak yang yakin, katanya, menurut mereka).
- Langsung BANDINGKAN secara visual: foto/rekaman terkenal dari kasusnya dengan tempat atau benda nyata yang mirip (sebut nama tempatnya kalau ada di BAHAN FAKTA), dengan kalimat seperti "Sekarang bandingkan dengan tempat ini di …" lalu jelaskan kemiripannya dengan dramatis. Pilih perbandingan yang mirip secara visual DAN menguatkan klaimnya (misalnya foto Bulan vs padang kawah tempat latihan astronaut di Arizona; peta bumi datar vs lambang PBB; foto Nessie vs fosil plesiosaurus), bukan dua hal sejenis yang tidak membuktikan apa-apa.
- Bagian tengah sepenuhnya dari sudut pandang orang-orang yang curiga: "bukti" dan kejanggalan satu per satu seperti detektif, ketegangan terus naik. Fakta nyata (misalnya tempat itu memang dipakai untuk latihan atau simulasi) boleh dipakai sebagai petunjuk yang menambah curiga. JANGAN menjelaskan versi resmi atau membantah di tengah video.
- Selipkan kalimat penggantung pendek seperti "Tapi ini baru permulaan.", "Dan di sinilah semuanya jadi aneh.", "Pertanyaannya: kenapa?"
- Baru di AKHIR: twist berupa kemungkinan atau teori "jalan tengah" yang mengejutkan (misalnya rekaman memang direka ulang karena keterbatasan teknologi), tetap dengan penanda "mungkin saja" atau "ada yang menduga".
- Setelah twist, cukup SATU kalimat singkat tentang apa yang sudah terbukti (tanpa menggurui), lalu satu pertanyaan ke penonton supaya berkomentar.""",
        "pendek": ("Alur: hook kecurigaan, perbandingan visual yang bikin merinding, kejanggalan-kejanggalan menurut "
                   "orang-orang yang curiga, twist kemungkinan jalan tengah, satu kalimat fakta, pertanyaan penutup."),
        "panjang": ("Alur: hook kecurigaan, perbandingan visual pertama, latar kejadian dari sudut pandang orang-orang yang curiga, "
                    "kejanggalan demi kejanggalan dengan ketegangan yang terus naik (fakta nyata dipakai sebagai petunjuk "
                    "yang menambah curiga), perbandingan atau kejanggalan paling besar, twist kemungkinan jalan tengah, "
                    "satu dua kalimat fakta yang sudah terbukti, pertanyaan penutup."),
    },
    # Menyusun teori besar dari bukti-bukti (raksasa, peradaban hilang, dll.), tanpa membantah di tengah.
    "bangun_teori": {
        "gaya": "Gayamu seperti narator channel misteri yang sedang menyusun teori besar dari bukti-bukti: penuh rasa takjub, misterius, membuat penonton merasa sedang menemukan sesuatu yang disembunyikan.",
        "aturan": """- Ikuti arahan dari TOPIK / CATATAN pembuat video (bukti yang ingin dibahas, sudut pandang, penutup), tetap dengan aturan di bawah.
- Kalimat pertama (maksimal 15 kata): pertanyaan besar atau kecurigaan, misalnya "Apakah raksasa pernah benar-benar hidup di Bumi?"
- Susun BUKTI demi BUKTI seperti yang diajukan orang-orang yang percaya teori ini. Pakai SEMUA bukti di catatan pembuat video, lalu tambahkan bukti, temuan, situs, atau legenda LAIN yang paling mengejutkan dari BAHAN FAKTA (tiap artikel di BAHAN FAKTA bisa jadi satu bukti). Jumlah bukti menyesuaikan panjang video: kira-kira satu bukti tiap 30 sampai 40 detik. Untuk tiap bukti: jelaskan apa bendanya dengan akurat (sesuai BAHAN FAKTA kalau ada), lalu kenapa banyak orang menganggapnya bukti, dengan penanda klaim. Klaim viral tanpa sumber disebut "foto yang viral menyebut…" atau "ada yang mengklaim…". Sebut nama benda, tempat, atau situs nyatanya kalau ada di BAHAN FAKTA (misalnya nama patung atau gunungnya dan di negara mana) supaya terasa nyata. Benda yang tidak ada di BAHAN FAKTA jangan ditulis "ditemukan" seolah fakta — pakai "beredar foto…", "konon…", atau "ada yang mengklaim…". Jangan mengarang lokasi, ukuran, tahun, atau nama penemu.
- Benda yang menurut BAHAN FAKTA sudah terbukti palsu atau hoaks (misalnya patung yang sengaja dibuat lalu dikubur) JANGAN disajikan sebagai bukti asli. Boleh diceritakan sebagai kisah yang sempat menggemparkan lalu terbongkar — itu menunjukkan betapa kuatnya orang ingin percaya.
- Rangkai bukti-bukti itu jadi satu teori besar, dengan kalimat penggantung antar bukti seperti "Tapi ini belum seberapa." atau "Dan bukti berikutnya lebih aneh lagi."
- Kalau teori ini memakai proses ilmiah (misalnya mineralisasi atau pembatuan), jelaskan prosesnya dengan BENAR sesuai BAHAN FAKTA, lalu sampaikan lompatan teorinya sebagai klaim ("menurut teori ini…", "bagaimana kalau…").
- Selain status hoaks di atas, jangan membantah atau menjelaskan versi resmi di tengah video.
- Penutup: satu kalimat jujur bahwa sampai sekarang belum ada bukti ilmiah yang memastikannya, jadi kita tidak pernah tahu pasti apakah ini nyata atau hanya teori; lalu satu pertanyaan ke penonton.""",
        "pendek": ("Alur: pertanyaan besar, bukti-bukti satu per satu menurut orang-orang yang percaya, mekanisme yang mereka "
                   "pakai, kalimat jujur bahwa belum terbukti, pertanyaan penutup."),
        "panjang": ("Alur: pertanyaan besar, latar legenda atau cerita kunonya, bukti demi bukti (tiap bukti: apa "
                    "bendanya + kenapa dianggap bukti) dengan ketegangan yang terus naik, mekanisme ilmiah yang dipakai "
                    "teori ini dan lompatan teorinya, rangkuman teori besarnya, kalimat jujur bahwa belum "
                    "terbukti, pertanyaan penutup."),
    },
    # Fakta sains seru: tebak-tebakan lalu jawabannya (asal-usul hewan, cara kerja alam, sejarah benda, dll.).
    "edukasi": {
        "gaya": "Gayamu seperti narator sains populer yang seru: tiap fakta diungkap seperti jawaban tebak-tebakan, bikin penonton bilang \"oh, ternyata!\".",
        "aturan": """- Ikuti arahan dan daftar di TOPIK / CATATAN pembuat video (hal yang dibahas, urutannya, fakta yang harus disebut), tetap dengan aturan di bawah.
- Ini video FAKTA, bukan teori: semua isi harus benar menurut BAHAN FAKTA, catatan pembuat video, atau pengetahuan ilmiah yang sangat umum. Penanda klaim ("banyak yang mengira…", "katanya…") hanya untuk mitos atau anggapan keliru. Kalau ragu, jangan sebut angka.
- Kalimat pertama (maksimal 15 kata): pertanyaan atau fakta yang bikin penasaran.
- Bahas SATU PER SATU sesuai daftar: perkenalkan hal itu dengan detail yang bisa dilihat penonton (bentuk, ciri, kebiasaan), lempar tebakan ("kira-kira dari mana asalnya?"), lalu ungkap jawabannya dengan nama yang benar plus satu bukti konkret (fosil, ciri tubuh, penelitian) dari BAHAN FAKTA atau catatan.
- Luruskan mitos yang populer dengan jelas tanpa menggurui ("Banyak yang mengira…, padahal…").
- Penutup: satu kesimpulan yang mengikat semuanya, lalu satu pertanyaan ke penonton.""",
        "pendek": ("Alur: hook pertanyaan, dua sampai empat hal satu per satu (tebakan → jawaban → bukti), satu mitos "
                   "yang diluruskan, kesimpulan, pertanyaan penutup."),
        "panjang": ("Alur: hook pertanyaan, latar singkat yang dibutuhkan supaya paham, hal demi hal satu per satu "
                    "(tebakan → jawaban → bukti konkret), mitos-mitos yang diluruskan, kesimpulan besar, pertanyaan "
                    "penutup."),
    },
    # Edukatif seimbang (gaya lama).
    "seimbang": {
        "gaya": "Gayamu: bercerita, menegangkan, bikin penasaran sampai akhir, tapi jujur ke penonton.",
        "aturan": """- Kalimat pertama adalah hook pendek (maksimal 15 kata) yang bikin orang berhenti scroll.
- Menjelang akhir, sampaikan penjelasan resmi atau ilmiah secara singkat dan adil. Untuk klaim yang bertentangan dengan bukti ilmiah (misalnya bumi datar), ceritakan apa yang dipercaya banyak orang dengan penanda klaim, lalu sebutkan bukti yang menunjukkan sebaliknya. Untuk makhluk legendaris, jelaskan asal-usul legendanya, penampakan yang terkenal, dan penjelasan ilmiahnya.
- Tutup dengan satu kalimat pertanyaan ke penonton supaya mereka berkomentar.""",
        "pendek": "Alur: hook, inti teori, satu kejanggalan paling menarik, penjelasan resmi singkat, pertanyaan penutup.",
        "panjang": ("Alur: hook, latar belakang kejadian, isi teorinya dan \"bukti\" yang diajukan orang-orang yang percaya, "
                    "kejanggalan yang bikin orang curiga, penjelasan resmi atau ilmiah, lalu penutup."),
    },
}


# Pengguna: "ceritanya belum clear, masih gantung, yang nonton masih 'apasih'". Naskah Area 51 menumpuk fakta
# (CIA 1955, U-2, 928 ledakan nuklir) tanpa pernah menyebut teorinya, tanpa "artinya apa", lalu ditutup dengan
# pertanyaan baru. Aturan ini tidak dipakai reels teaser (yang memang sengaja berhenti di titik penasaran).
_KEJELASAN = """SUPAYA PENONTON LANGSUNG NANGKEP (paling penting):
- Dalam tiga kalimat pertama penonton sudah tahu video ini membahas apa DAN teorinya apa. Sebut teorinya dengan kalimat konkret ("Teorinya begini: …", "Banyak yang yakin …"), bukan cuma "ada yang aneh" atau "bukan sekadar teori".
- Anggap penonton belum tahu apa-apa: kenalkan tempat, tokoh, atau istilah dalam satu kalimat sederhana (misalnya "U-2, pesawat mata-mata Amerika").
- Setiap fakta langsung diikuti alasannya: "artinya…", "kenapa ini penting? karena…". Jangan menumpuk fakta tanpa menjelaskan hubungannya dengan teori.
- Satu garis cerita: semua kalimat mendukung pertanyaan besar itu. Fakta menarik yang tidak nyambung dibuang.
- Pertanyaan besar di awal HARUS terjawab di akhir: rangkum buktinya dalam satu kalimat lalu tulis jawaban versi teorinya dengan jelas (tetap dengan penanda klaim, misalnya "Kalau semua digabung, wajar banyak yang yakin …"). Jangan menutup dengan teka-teki baru yang belum pernah dibahas."""


_KEJELASAN_FAKTA = """SUPAYA PENONTON LANGSUNG NANGKEP (paling penting):
- Dalam tiga kalimat pertama penonton sudah tahu video ini membahas apa DAN pertanyaan besar apa yang akan dijawab.
- Anggap penonton belum tahu apa-apa: kenalkan tempat, benda, atau istilah dalam satu kalimat sederhana.
- Setiap fakta langsung diikuti artinya atau kenapa itu penting. Jangan menumpuk angka tanpa penjelasan.
- Satu garis cerita: semua kalimat membantu menjawab pertanyaan besar itu. Fakta menarik yang tidak nyambung dibuang.
- Pertanyaan besar di awal HARUS terjawab dengan jelas sebelum video selesai. Jangan menutup dengan teka-teki baru."""


def sistem(gaya="twist"):
    g = GAYA_NASKAH.get(gaya, GAYA_NASKAH["twist"])
    kejelasan = _KEJELASAN_FAKTA if gaya in GAYA_FAKTA else _KEJELASAN
    # _PERAN menyebut channel misteri/konspirasi; channel fakta memakai peran sendiri
    peran = _PERAN_FAKTA if gaya in GAYA_FAKTA else _PERAN
    return f"{peran}\n{g['gaya']}\n\nATURAN:\n{g['aturan']}\n{kejelasan}\n{_ATURAN_UMUM}"


GAYA_FAKTA = ("sains", "edukasi")  # bukan teori/konspirasi
_PERAN_FAKTA = """Kamu penulis naskah voice-over untuk channel YouTube/TikTok berbahasa Indonesia tentang sains, alam, dan penemuan: bumi, luar angkasa, hewan, sejarah, arkeologi, teknologi.
Isinya FAKTA yang bisa dipertanggungjawabkan, disampaikan dengan seru."""
GAYA_BERINTI = ("meyakinkan", "twist", "bangun_teori", "sains")  # naskah ditulis dari inti_cerita
SCHEMA_INTI = {  # kolom datar + bukti bernomor (array membuat gemma mengulang token)
    "type": "object",
    "properties": {"pertanyaan": {"type": "string"}, "teori": {"type": "string"}, "konteks": {"type": "string"},
                   "fakta_1": {"type": "string"}, "artinya_1": {"type": "string"},
                   "fakta_2": {"type": "string"}, "artinya_2": {"type": "string"},
                   "fakta_3": {"type": "string"}, "artinya_3": {"type": "string"},
                   "versi_resmi": {"type": "string"}, "kesimpulan": {"type": "string"}, "hook": {"type": "string"}},
    "required": ["pertanyaan", "teori", "konteks", "fakta_1", "artinya_1", "fakta_2", "artinya_2", "fakta_3",
                 "artinya_3", "versi_resmi", "kesimpulan", "hook"],
}


def inti_cerita(cfg, bahan, riset, batal=None, log=print, gaya="meyakinkan"):
    """Rencana satu garis cerita sebelum naskah ditulis: pertanyaan besar → teorinya (video fakta: jawaban para
    ilmuwan) → 3 fakta nyata + "artinya" → versi resmi → kesimpulan yang menjawab pertanyaan. Model 12B yang langsung
    menulis naskah sering menumpuk fakta tanpa klaim yang jelas. Mengembalikan teks rencana, atau "" kalau gagal
    (naskah tetap ditulis tanpa rencana)."""
    fakta = gaya in GAYA_FAKTA
    kolom = (
        "- pertanyaan: satu pertanyaan besar yang dijawab video ini, yang bikin orang awam penasaran.\n"
        "- teori: JAWABAN singkat para ilmuwan atas pertanyaan itu (apa penyebabnya / apa yang sebenarnya terjadi).\n"
        "- konteks: satu kalimat pengenalan untuk penonton yang belum tahu apa-apa (apa, di mana, seberapa besar).\n"
        "- fakta_1..3: fakta NYATA dari BAHAN FAKTA (dengan tahun, ukuran, jarak, atau angka) yang menjelaskan "
        "jawabannya, berurutan dari yang paling mudah dipahami ke yang paling mengejutkan.\n"
        "- artinya_1..3: arti fakta itu bagi orang awam, sebaiknya dengan analogi sehari-hari atau pembanding skala.\n"
        "- versi_resmi: hal yang masih belum diketahui atau masih diteliti para ilmuwan (isi \"-\" kalau tidak ada).\n"
        "- kesimpulan: kalimat penutup yang MENJAWAB pertanyaan besar sekaligus dampaknya yang bikin wow.\n"
        "- hook: DUA kalimat pembuka video (masing-masing maksimal 14 kata): fakta paling mengejutkan di atas yang "
        "bisa langsung dibayangkan (pakai angka atau perbandingan), lalu kontras \"Tapi…\" yang memancing pertanyaan "
        "besar. Bukan pengantar, bukan definisi.\n"
        "Semua harus fakta dari BAHAN FAKTA atau pengetahuan ilmiah yang sangat umum, tanpa teori konspirasi."
        if fakta else
        "- pertanyaan: satu pertanyaan besar yang dijawab video ini, yang bikin orang awam penasaran.\n"
        "- teori: jawaban versi teori konspirasinya, KONKRET (siapa menyembunyikan apa / apa yang sebenarnya terjadi), "
        "diawali \"Banyak yang yakin\".\n"
        "- konteks: satu kalimat pengenalan untuk penonton yang belum tahu apa-apa (apa, di mana, kapan).\n"
        "- fakta_1..3: fakta NYATA dari BAHAN FAKTA (dengan tahun, nama, tempat, atau angka) yang paling mendukung "
        "teori itu, berurutan dari yang paling mudah dipahami ke yang paling mengejutkan.\n"
        "- artinya_1..3: kenapa fakta itu membuat teori tadi terasa masuk akal (jembatan logikanya), satu kalimat.\n"
        "- versi_resmi: penjelasan resmi atau ilmiah singkat yang adil.\n"
        "- kesimpulan: kalimat penutup yang MENJAWAB pertanyaan besar menurut teori, diawali \"Kalau semua "
        "digabung\".\n"
        "- hook: satu atau dua kalimat pembuka video (masing-masing maksimal 14 kata) yang langsung melempar "
        "kecurigaan terbesar sebagai klaim, dengan detail konkret. Bukan pengantar.\n"
        "Fakta, angka, dan nama hanya dari BAHAN FAKTA. Jangan menuduh orang nyata berbuat kejahatan.")
    # Awal prompt (system + BAHAN FAKTA + TOPIK) dibuat SAMA PERSIS dengan prompt penulisan naskah berikutnya, supaya
    # Ollama memakai ulang cache-nya. Di mini PC tanpa GPU, membaca ±8.000 token bahan riset makan ±20 menit.
    pesan = [{"role": "system", "content": sistem(gaya)}, {"role": "user", "content": (
        f"{_awal_bahan(riset, bahan)}"
        f"Sebelum naskah video {'sains/fakta' if fakta else 'konspirasi/misteri'} ditulis, susun INTI CERITANYA dalam "
        f"bahasa Indonesia sehari-hari, satu kalimat per kolom:\n{kolom}")}]
    try:
        j = ollama.chat_json(cfg, pesan, SCHEMA_INTI, batal=batal, maks_token=800, suhu=0.4)
    except (RuntimeError, ValueError) as e:
        log(f"Inti cerita gagal disusun ({e}) — naskah ditulis langsung")
        return ""
    bersih = {k: " ".join(str(j.get(k) or "").split()) for k in SCHEMA_INTI["required"]}
    if not bersih["pertanyaan"] or not bersih["teori"]:
        return ""
    log(f"Inti cerita: {bersih['pertanyaan']} → {bersih['teori']}")
    bukti = "\n".join(f"{n}. {bersih[f'fakta_{n}']} → artinya: {bersih[f'artinya_{n}']}" for n in (1, 2, 3)
                      if bersih[f"fakta_{n}"])
    # hook di baris pertama: dipakai sebagai kalimat pembuka naskah (dulu video dibuka "Jika kamu berdiri di puncak
    # Everest…" — pengantar pelan, penonton keburu pergi)
    return ((f"Hook pembuka (jadikan dua kalimat pertama naskah, boleh diperhalus): {bersih['hook']}\n"
             if bersih["hook"] else "")
            + f"Pertanyaan besar: {bersih['pertanyaan']}\n{'Jawaban para ilmuwan' if fakta else 'Teorinya'}: "
            f"{bersih['teori']}\nKonteks untuk penonton awam: {bersih['konteks']}\n"
            f"{'Penjelasan' if fakta else 'Bukti'} (fakta → artinya):\n{bukti}\n"
            f"{'Yang masih diteliti' if fakta else 'Versi resmi'}: {bersih['versi_resmi']}\n"
            f"Kesimpulan yang menjawab pertanyaan: {bersih['kesimpulan']}")


def _perintah_inti(inti):
    return (f"INTI CERITA (ikuti garis ini; boleh diperhalus, jangan menambah fakta di luar BAHAN FAKTA):\n{inti}\n\n"
            if inti else "")




def target_kata(durasi):
    return max(60, int(durasi * KATA_PER_DETIK))


def bersihkan(teks):
    teks = teks.replace("\r", "")
    teks = re.sub(r"[*_#`>]+", "", teks)
    teks = re.sub(r"^\s*(hook|narator|narasi|penutup|intro|outro|judul|scene|adegan)\s*\d*\s*:\s*", "", teks,
                  flags=re.I | re.M)
    teks = re.sub(r"\[[^\]]*\]|\((musik|visual|sfx|jeda|footage)[^)]*\)", "", teks, flags=re.I)
    teks = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", teks)
    teks = re.sub(r"[ \t]+", " ", teks)
    teks = re.sub(r"\b(\w{4,}) atau \1\b", r"\1", teks, flags=re.I)  # "petrifikasi atau petrifikasi"
    teks = _tanpa_penganut(teks)
    teks = re.sub(r"\n\s*\n+", "\n\n", teks)
    return teks.strip()


# "Para penganut teori konspirasi percaya…" terdengar kaku dan mengejek; pengguna mau gaya ngobrol
# ("Banyak yang tidak percaya…"). Saringan terakhir kalau model masih menulisnya.
_PENGANUT = re.compile(r"\b(?:para\s+)?(?:penganut|pendukung|pengikut|pengamat|pemercaya)\s+teori"
                       r"(?:\s+konspirasi)?(?:\s+(?:ini|itu|tersebut|besar|bumi datar))?|\b(?:para\s+)?penganutnya\b", re.I)


def _tanpa_penganut(teks):
    def ganti(m):
        sisa = teks[m.end():m.end() + 40].lower()
        pengganti = "orang-orang yang curiga" if re.match(r"\s*\S+\s+banyak\b", sisa) else "banyak orang"
        return pengganti
    teks = _PENGANUT.sub(ganti, teks)
    teks = re.sub(r"\b[Mm]enurut banyak orang,\s*", "Banyak yang yakin, ", teks)
    # huruf besar di awal kalimat
    return re.sub(r"(^|[.!?]\s+|\n\s*)(banyak orang|orang-orang yang curiga)",
                  lambda m: m.group(1) + m.group(2)[0].upper() + m.group(2)[1:], teks)


def _buang_ulangan(sebelumnya, teks):
    """Bagian baru kadang membuka dengan kalimat penutup bagian sebelumnya ("Namun, keanehan ini tidak berhenti
    pada bentang alam saja." lalu "Keanehan ini tidak berhenti pada bentang alam saja, karena ..." dibacakan
    berturut-turut). Kalimat penutup bagian sebelumnya yang hampir sama, atau yang kata-katanya sudah termuat di
    kalimat pembuka bagian baru, dibuang dari bagian sebelumnya. Mengembalikan (sebelumnya, teks)."""
    akhir, awal = pecah_kalimat(sebelumnya), pecah_kalimat(teks)
    if len(akhir) < 2 or not awal:
        return sebelumnya, teks
    a = set(re.findall(r"\w+", akhir[-1].lower())) - {"namun", "tapi", "dan", "bahkan"}
    b = set(re.findall(r"\w+", awal[0].lower()))
    mirip = difflib.SequenceMatcher(None, akhir[-1].lower(), awal[0].lower()).ratio() > 0.75
    if mirip or (a and len(a & b) / len(a) >= 0.8):
        posisi = sebelumnya.rfind(akhir[-1][:30])
        if posisi > 0:
            sebelumnya = sebelumnya[:posisi].rstrip()
    return sebelumnya, teks


_PENYAMBUNG = {"namun", "tapi", "tetapi", "dan", "bahkan", "lalu", "kemudian", "jadi", "nah", "sementara", "padahal",
               "ternyata", "faktanya", "sebenarnya"}


def buang_fakta_berulang(teks):
    """Model 12B sering menutup video panjang dengan rangkuman "Pertama… Kedua… Ketiga…" yang mengulang semua angka
    (naskah Palung Mariana menyebut 1.600 gajah, 1.071 kali tekanan, dan suhu 1-4 derajat masing-masing dua kali) —
    terasa bertele-tele. Kalimat yang angkanya SEMUA sudah pernah disebut dan kata-katanya sebagian besar sama dengan
    kalimat terdahulu dibuang; begitu juga kalimat tanpa angka baru yang hampir semua katanya sudah pernah diucapkan
    ("Pertama, Palung Mariana terbentuk karena proses subduksi." di rangkuman: 14% kata baru). Juga kalimat tanpa
    angka baru yang 6 kata pertamanya sama dengan kalimat terdahulu: "Himalaya adalah barisan pegunungan raksasa di
    Asia yang…" pernah membuka dua bagian berturut-turut."""
    sudah_angka, sudah_kata, semua, sudah_awal, hasil = set(), [], set(), set(), []
    for par in teks.split("\n\n"):
        simpan = []
        for k in pecah_kalimat(par):
            angka = set(re.findall(r"\d+(?:[.,]\d+)*", k))
            kata = {w for w in re.findall(r"\w+", k.lower()) if len(w) > 3}
            awal = re.findall(r"\w+", k.lower())
            while awal and awal[0] in _PENYAMBUNG:  # "Namun, Himalaya adalah…" = "Himalaya adalah…"
                awal.pop(0)
            awal = tuple(awal[:6])
            mirip = max((len(kata & lama) / len(kata) for lama in sudah_kata), default=0) if kata else 0
            baru = len(kata - semua) / len(kata) if kata else 1
            if not (angka - sudah_angka) and ((angka and mirip >= 0.45) or (len(kata) >= 5 and mirip >= 0.8)
                                              or (len(kata) >= 7 and baru <= 0.15)
                                              or (len(awal) == 6 and awal in sudah_awal)):
                continue
            simpan.append(k)
            sudah_angka |= angka
            sudah_kata.append(kata)
            semua |= kata
            sudah_awal.add(awal)
        if simpan:
            hasil.append(" ".join(simpan))
    teks = "\n\n".join(hasil)
    if not re.search(r"(^|[.!?]\s+|\n)Pertama\b", teks):  # "Pertama…" terbuang: "Kedua," jadi tanpa nomor
        teks = re.sub(r"(^|[.!?]\s+|\n)(?:Kedua|Ketiga|Keempat|Kelima|Terakhir)\s*,\s*(\w)",
                      lambda m: m.group(1) + m.group(2).upper(), teks)
    return teks


_PEMBANDING = re.compile(r"\b(daripada|dibandingkan?|setara|kali lipat|seukuran|setinggi|sebesar|seberat|seluas|"
                         r"secepat|sepanjang|lebih (cepat|lambat|besar|kecil|tinggi|rendah|panjang|berat|tua|dalam|"
                         r"luas|banyak))\b", re.I)
# perbandingan DENGAN sesuatu ("lebih cepat daripada kuku", "setara 1.600 gajah") — "tumbuh lebih tinggi" saja bukan
_BANDING_OBJEK = re.compile(r"\b(daripada|dibandingkan?|setara|kali lipat|(seukuran|setinggi|sebesar|seberat|seluas|"
                            r"secepat|sepanjang)(?!\s+(ini|itu|apa)\b))\b", re.I)  # "energi sebesar ini" bukan pembanding
# kata yang wajar muncul di perbaikan walau tidak ada di naskah/sumber (arah perbandingan, keterangan waktu)
_KATA_PERBAIKAN = {"lambat", "cepat", "kecil", "besar", "rendah", "tinggi", "pendek", "panjang", "ringan", "berat",
                   "muda", "sedikit", "banyak", "awalnya", "dahulu", "mula-mula", "sekitar", "hampir", "kurang",
                   "lebih", "kira-kira", "semula", "sekarang"}


_SATUAN = {"cm": "cm", "sentimeter": "cm", "centimeter": "cm", "centimetre": "cm", "centimetres": "cm",
           "mm": "mm", "milimeter": "mm", "millimetre": "mm", "km": "km", "kilometer": "km", "kilometre": "km",
           "kilometres": "km", "m": "m", "meter": "m", "metre": "m", "metres": "m", "juta": "juta", "million": "juta",
           "mya": "juta", "ma": "juta", "miliar": "miliar", "billion": "miliar", "ribu": "ribu", "thousand": "ribu",
           "persen": "%", "percent": "%", "%": "%", "derajat": "derajat", "degrees": "derajat", "ton": "ton",
           "tons": "ton", "tonnes": "ton", "kg": "kg", "kilogram": "kg", "tahun": "tahun", "year": "tahun",
           "years": "tahun", "bar": "bar"}


def _angka(teks):
    """Angka tanpa pemisah ribuan/desimal: "1.600" dan "1,600" sama-sama "1600"."""
    return {re.sub(r"[.,]", "", x) for x in re.findall(r"\d+(?:[.,]\d+)*", teks)}


def _angka_satuan(teks):
    """Pasangan (angka, satuan): "20 cm" ↔ "20 cm (7.9 in)", "25 juta tahun" ↔ "~25 Mya" — supaya "20" tidak
    tertukar dengan "20th century"."""
    return {(re.sub(r"[.,]", "", a), _SATUAN.get(s.lower())) for a, s in
            re.findall(r"(\d+(?:[.,]\d+)*)\s*(%|[A-Za-z]+)?", teks) if _SATUAN.get((s or "").lower())}


# kata umum yang tidak menunjukkan dua kalimat membahas hal yang sama
_KATA_LEMAH = {"sekitar", "dengan", "bahwa", "mereka", "sangat", "dalam", "untuk", "adalah", "karena", "tetapi",
               "namun", "menjadi", "hingga", "setelah", "sebelum", "sebagai", "seperti", "tersebut", "lebih", "tahun",
               "bahkan", "ternyata", "sebenarnya", "about", "which", "their", "there", "after", "before", "years",
               "million", "would", "these", "those", "being", "other", "where", "while"}


def _kutipan_sumber(kalimat, sumber):
    """Dua kalimat sumber yang memuat angka yang sama (satuan yang sama didahulukan) dengan kalimat naskah. Tanpa
    angka yang sama (angka ditulis dengan huruf: "sembilan juta kilometer persegi"), kalimat sumber dengan kata yang
    paling banyak sama — dulu kutipannya kosong dan luas Sahara yang benar dibuang karena "tidak ada di sumber"."""
    angka, pasangan = _angka(kalimat), _angka_satuan(kalimat)
    kata = {w for w in re.findall(r"\w+", kalimat.lower()) if len(w) > 4} - _KATA_LEMAH
    # Angka yang ada di banyak kalimat sumber (tahun peristiwanya: "1883" di 18 kalimat) bukan penanda: dulu kalimat
    # "gelombang tekanan mengelilingi dunia lebih dari tiga kali" mendapat kutipan tentang gempa tahun 1883, padahal
    # sumbernya memuat kalimat yang hampir sama persis.
    umum = {a for a in angka if sum(1 for s in sumber if a in _angka(s)) >= 5}
    skor = []
    for s in sumber:
        angka_s = _angka(s)
        khas = (angka - umum) & angka_s
        mirip = len(kata & set(re.findall(r"\w+", s.lower())))
        if khas or mirip >= 2:
            skor.append((3 * len(khas) + 3 * len(pasangan & _angka_satuan(s)) + 0.5 * len(angka & umum & angka_s)
                         + mirip, s))
    return [s for _, s in sorted(skor, key=lambda x: -x[0])[:2]]


_DULU_SUMBER = re.compile(r"\b(began|begun|initially|originally|used to|at that time|formerly|at first|"
                          r"in the past|mula-mula|awalnya|dahulu)\b", re.I)
_DULU_NASKAH = re.compile(r"\b(dulu|dahulu|awalnya|mulanya|semula|mulai|pernah|sempat|saat itu|kala itu|ketika itu|"
                          r"yang lalu|silam|sebelum|pada awalnya)\b", re.I)


def _catatan_waktu(kalimat, kutipan):
    """Petunjuk pasti untuk pemeriksa: kutipan yang memuat angka+satuan yang sama memakai keterangan masa lalu/awal,
    kalimat naskah tidak. Tanpa petunjuk ini model kadang menangkap "bergerak 20 cm per tahun" (sumber: began
    moving), kadang tidak."""
    if _DULU_NASKAH.search(kalimat):
        return ""
    pasangan = _angka_satuan(kalimat)
    for s in kutipan:
        m = _DULU_SUMBER.search(s)
        if m and pasangan & _angka_satuan(s):
            return (f"\n   Catatan: kutipan memakai keterangan masa lalu/awal (\"{m.group(0)}\"), kalimat naskah "
                    "menulisnya seolah berlaku sekarang.")
    return ""


def periksa_fakta(cfg, teks, riset, batal=None, log=print):
    """Kalimat naskah yang memuat angka atau perbandingan dicek model teks terhadap kalimat sumber yang memuat angka
    yang sama. Dulu sumber "began moving north at about 20 cm per year" (dulu) ditulis "bergerak 20 cm per tahun"
    (sekarang), dan "10 mm per tahun" disebut lebih cepat daripada tumbuhnya kuku (kuku ±3 cm per tahun). Kalimat yang
    salah diganti perbaikan dari model, atau dibuang — setelah usulannya lolos pemeriksa kedua (_uji_usulan).
    Mengembalikan (teks, {kalimat lama: kalimat baru atau ""})."""
    sumber = [x.strip() for s in riset for x in re.split(r"(?<=[.!?])\s+|\n+", s.get("teks") or "") if len(x) > 20]
    paragraf = [pecah_kalimat(p) for p in teks.split("\n\n")]
    periksa = [(pi, ki) for pi, par in enumerate(paragraf) for ki, k in enumerate(par)
               if (re.search(r"\d", k) or _BANDING_OBJEK.search(k)) and not k.rstrip().endswith("?")][:24]
    ganti, usulan = {}, []
    dikenal = _KATA_PERBAIKAN | set(re.findall(r"[\w-]+", (teks + " " + " ".join(s.get("teks") or "" for s in riset))
                                               .lower()))
    # Keterangan waktu yang hilang dideteksi kode (model 12B menangkapnya kadang-kadang saja, walau sudah diberi
    # catatan); model hanya menulis ulang kalimatnya.
    waktu = [(pi, ki) for pi, ki in periksa
             if _catatan_waktu(paragraf[pi][ki], _kutipan_sumber(paragraf[pi][ki], sumber))]
    if waktu:
        for (pi, ki), baru in zip(waktu, _tulis_ulang_waktu(cfg, [paragraf[pi][ki] for pi, ki in waktu], batal,
                                                            dikenal)):
            lama = paragraf[pi][ki]
            ganti[lama] = paragraf[pi][ki] = baru
            log(f"Keterangan waktu diperbaiki: «{lama}» → «{baru or '(dibuang)'}»")
        periksa = [x for x in periksa if x not in waktu]
    for mulai in range(0, len(periksa), 8):
        if batal:
            batal.cek()
        kelompok = periksa[mulai:mulai + 8]
        daftar = []
        for n, (pi, ki) in enumerate(kelompok):
            k = paragraf[pi][ki]
            kutip = _kutipan_sumber(k, sumber)
            # kalimat sebelumnya ikut ditulis: "Angka ini … lebih cepat daripada kuku" merujuk "10 mm per tahun" di
            # kalimat sebelumnya — tanpa itu pemeriksa kadang tidak bisa menghitungnya
            sebelum = paragraf[pi][ki - 1] if ki > 0 else (paragraf[pi - 1][-1] if pi > 0 and paragraf[pi - 1] else "")
            daftar.append(f"{n + 1}) {k}\n"
                          + (f"   Kalimat sebelumnya (konteks, tidak diperiksa): {sebelum}\n" if sebelum else "")
                          + "   Kutipan sumber: "
                          + (" | ".join(x[:300] for x in kutip) if kutip else "(tidak ada angka yang sama di sumber)")
                          + _catatan_waktu(k, kutip))
        schema = {"type": "object", "properties": {"kalimat": {
            "type": "array", "minItems": len(kelompok), "maxItems": len(kelompok), "items": {
                "type": "object", "required": ["no", "alasan", "benar", "perbaikan"],
                "properties": {"no": {"type": "integer"}, "alasan": {"type": "string"},
                               "benar": {"type": "boolean"}, "perbaikan": {"type": "string"}}}}},
            "required": ["kalimat"]}
        pesan = [{"role": "user", "content": (
            "Kamu pemeriksa fakta naskah video sains berbahasa Indonesia. Periksa tiap kalimat di bawah terhadap "
            "kutipan sumbernya dan pengetahuan ilmiah yang sudah pasti.\n\n" + "\n".join(daftar) + "\n\n"
            "Kalimat SALAH kalau:\n"
            "- angka, satuan, atau acuannya berbeda dari kutipan sumber;\n"
            "- keterangan waktunya berubah: kutipan menyebut keadaan dulu atau di awal (kata seperti began, initially, "
            "was, were, once, used to, at that time, million years ago), tapi naskah menulisnya seolah berlaku "
            "sekarang (\"sebenarnya bergerak …\", \"saat ini …\", tanpa kata dulu/awalnya);\n"
            "- perbandingannya keliru: hitung kedua angka dalam satuan yang sama (misalnya rambut tumbuh ±1 cm per "
            "bulan = ±12 cm per tahun), lalu cek arah \"lebih cepat/lebih besar\";\n"
            "- klaimnya tidak ada di sumber DAN menurut pengetahuan ilmiah yang sudah pasti memang keliru atau "
            "meragukan. Kalimat yang tidak ada di kutipan tapi benar menurut pengetahuan umum (misalnya luas atau "
            "tinggi yang terkenal) tetap benar.\n"
            "Analogi tanpa angka (\"seperti karpet yang ditekuk\"), gaya bahasa, dan pertanyaan dianggap benar.\n"
            "alasan: satu kalimat pendek, tulis hitungannya kalau ada perbandingan. perbaikan: kalau salah, kalimat "
            "pengganti yang benar dengan gaya yang sama (angka hanya dari kutipan sumber); \"\" kalau benar atau kalau "
            "kalimatnya lebih baik dibuang.")}]
        try:
            j = ollama.chat_json(cfg, pesan, schema, batal=batal, maks_token=90 * len(kelompok) + 80, suhu=0.1)
        except (RuntimeError, ValueError) as e:
            log(f"Pemeriksaan fakta dilewati ({e})")
            continue
        hasil = [x for x in j.get("kalimat", []) if isinstance(x, dict)]
        salah = [x for x in hasil if x.get("benar") is False and 1 <= _int(x.get("no")) <= len(kelompok)]
        if len(salah) > max(2, len(kelompok) * 0.6):  # hampir semua dianggap salah: pemeriksanya yang ngawur
            log(f"Pemeriksaan fakta diabaikan: {len(salah)} dari {len(kelompok)} kalimat dianggap salah")
            continue
        sudah = set()
        for x in salah:
            if _int(x["no"]) in sudah:  # nomor ganda dari model: dulu satu kalimat diubah 25 → 55 → 25 juta
                continue
            sudah.add(_int(x["no"]))
            pi, ki = kelompok[_int(x["no"]) - 1]
            lama = paragraf[pi][ki]
            baru = " ".join(str(x.get("perbaikan") or "").split())
            if baru == " ".join(lama.split()):  # "salah" tapi perbaikannya sama persis: tidak ada yang diubah
                continue
            if len(baru.split()) > 2 * len(lama.split()) + 5:
                baru = ""
            if baru and _BANDING_OBJEK.search(lama) and _angka(baru) == _angka(lama) and _pembanding(baru) == \
                    _pembanding(lama):
                # dinilai salah tapi "perbaikannya" tetap "lebih cepat daripada kuku": kalimatnya dibuang saja
                baru = ""
            asing = [w for w in re.findall(r"[\w-]+", baru.lower()) if len(w) >= 5 and w not in dikenal]
            if asing:  # perbaikan berisi kata rusak ("tabisasi"): perbandingan yang salah dibuang, lainnya dibiarkan
                log(f"Usulan perbaikan berisi kata asing {asing}: «{baru}»")
                if not _BANDING_OBJEK.search(lama):
                    continue
                baru = ""
            usulan.append({"letak": (pi, ki), "lama": lama, "baru": baru, "alasan": str(x.get("alasan") or ""),
                           "kutipan": _kutipan_sumber(lama, sumber),
                           "sebelum": paragraf[pi][ki - 1] if ki > 0 else ""})
    for u, ok in zip(usulan, _uji_usulan(cfg, usulan, batal, log)):
        if not ok:
            log(f"Usulan perbaikan ditolak pemeriksa kedua: «{u['lama']}» → «{u['baru'] or '(dibuang)'}»")
            continue
        pi, ki = u["letak"]
        ganti[u["lama"]] = u["baru"]
        paragraf[pi][ki] = u["baru"]
        log(f"Fakta diperbaiki: «{u['lama']}» → «{u['baru'] or '(dibuang)'}» ({u['alasan'][:150]})")
    teks = "\n\n".join(" ".join(k for k in par if k) for par in paragraf)
    return "\n\n".join(p for p in teks.split("\n\n") if p.strip()), ganti


def _pembanding(teks):
    return {m.group(0).lower() for m in _PEMBANDING.finditer(teks)}


def _tulis_ulang_waktu(cfg, kalimat, batal, dikenal):
    """Kalimat yang angkanya menurut sumber berlaku dulu/di awal ditulis ulang supaya jelas waktunya. Hasil yang
    tidak memuat keterangan masa lalu, mengubah angkanya, atau berisi kata rusak ditolak, kalimatnya dibuang ("")."""
    props = {f"kalimat_{n + 1}": {"type": "string"} for n in range(len(kalimat))}
    pesan = [{"role": "user", "content": (
        "Kalimat naskah video berikut menyebut angka yang menurut sumbernya berlaku DULU atau DI AWAL, tapi ditulis "
        "seolah berlaku sekarang:\n\n" + "\n".join(f"{n + 1}) {k}" for n, k in enumerate(kalimat)) + "\n\n"
        "Tulis ulang tiap kalimat dalam bahasa Indonesia dengan gaya yang sama supaya jelas angkanya berlaku dulu "
        "atau di awal (pakai kata seperti dulu, awalnya, mula-mula, saat itu). Angkanya jangan diubah.")}]
    try:
        j = ollama.chat_json(cfg, pesan, {"type": "object", "properties": props, "required": list(props)},
                             batal=batal, maks_token=60 * len(kalimat) + 40, suhu=0.2)
    except (RuntimeError, ValueError):
        j = {}
    hasil = []
    for n, k in enumerate(kalimat):
        baru = " ".join(str(j.get(f"kalimat_{n + 1}") or "").split())
        ok = baru and _DULU_NASKAH.search(baru) and _angka(k) <= _angka(baru) \
            and len(baru.split()) <= 2 * len(k.split()) + 5 \
            and all(w in dikenal for w in re.findall(r"[\w-]+", baru.lower()) if len(w) >= 5)
        hasil.append(baru if ok else "")
    return hasil


def _uji_usulan(cfg, usulan, batal, log):
    """Pemeriksa kedua: tiap usulan perbaikan dibandingkan dengan kalimat aslinya terhadap kutipan sumber yang sama.
    Pemeriksa pertama pernah "membetulkan" tabrakan keras 25 juta tahun lalu (benar menurut sumber) jadi 55 juta, dan
    20 cm/tahun jadi "0 hingga 10 cm" dari kalimat sumber lain. Mengembalikan list bool (True = usulan dipakai)."""
    if not usulan:
        return []
    daftar = "\n".join(
        f"{n + 1}) " + (f"Kalimat sebelumnya (konteks): {u['sebelum']}\n   " if u.get("sebelum") else "")
        + f"ASLI: {u['lama']}\n   USULAN: {u['baru'] or '(kalimat dibuang)'}\n   Kutipan sumber: "
        + (" | ".join(x[:300] for x in u["kutipan"]) or "(tidak ada)") + _catatan_waktu(u["lama"], u["kutipan"])
        for n, u in enumerate(usulan))
    props = {f"usulan_{n + 1}": {"type": "boolean"} for n in range(len(usulan))}
    pesan = [{"role": "user", "content": (
        "Untuk tiap nomor, bandingkan kalimat ASLI dan USULAN dengan kutipan sumbernya dan pengetahuan ilmiah yang "
        "sudah pasti.\n\n" + daftar + "\n\n"
        "usulan_N = true hanya kalau USULAN lebih sesuai dengan kutipan sumber daripada ASLI (angka, satuan, keterangan "
        "waktu dulu/sekarang, arah perbandingan). false kalau ASLI sudah sesuai sumber, kalau kutipannya membahas hal "
        "lain sehingga tidak membuktikan ASLI salah (kecuali ASLI jelas keliru menurut pengetahuan ilmiah yang sudah "
        "pasti), kalau USULAN mengambil angka dari kalimat sumber yang membahas hal lain, atau kalau USULAN merusak "
        "kalimatnya.")}]
    try:
        j = ollama.chat_json(cfg, pesan, {"type": "object", "properties": props, "required": list(props)},
                             batal=batal, maks_token=12 * len(usulan) + 30, suhu=0.1)
    except (RuntimeError, ValueError) as e:
        log(f"Pemeriksa kedua gagal ({e}) — naskah tidak diubah")
        return [False] * len(usulan)
    return [j.get(f"usulan_{n + 1}") is True for n in range(len(usulan))]


def _fakta(riset):
    return "\n\n".join(f"[{s['judul']} — Wikipedia {s['lang']}]\n{s['teks']}" for s in riset) or "(tidak ada)"


def _awal_bahan(riset, bahan):
    """Awal pesan pengguna yang sama untuk inti cerita, naskah pendek, dan kerangka/bagian naskah panjang (cache)."""
    return (f"BAHAN FAKTA (sumber terpercaya, pakai untuk detail):\n{_fakta(riset)}\n\n"
            f"TOPIK / CATATAN DARI PEMBUAT VIDEO:\n{bahan.strip()}\n\n")


def _perintah_cta(cta):
    cta = (cta or "").strip()
    return (f" Pertanyaan ke penonton tetap ditulis, lalu SESUDAHNYA kalimat paling akhir naskah adalah ajakan ini "
            f"(boleh sedikit disesuaikan supaya mengalir): «{cta}»" if cta else "")


def tulis(cfg, bahan, riset, durasi, batal=None, saat_token=None, log=print, gaya="twist", cta=""):
    """Mengembalikan (naskah, bab). Video > 3 menit ditulis per bagian (bab dipakai untuk chapter YouTube)."""
    inti = inti_cerita(cfg, bahan, riset, batal, log, gaya=gaya) if gaya in GAYA_BERINTI else ""
    if durasi > 180:
        return _tulis_panjang(cfg, bahan, riset, durasi, batal, saat_token, log, gaya, cta, inti=inti)
    g = GAYA_NASKAH.get(gaya, GAYA_NASKAH["twist"])
    kata = target_kata(durasi)
    lebih = max(10, kata // 10)
    # Dengan inti cerita 3 bukti, naskah 45 detik pernah jadi 174 kata (target 99, narasi 77 detik).
    ringkas = (" Video ini pendek: pakai DUA bukti terkuat saja dari INTI CERITA, dan versi resmi + sikap pribadi "
               "cukup satu atau dua kalimat." if inti and durasi <= 75 else "")
    pesan = [
        {"role": "system", "content": sistem(gaya)},
        {"role": "user", "content": (
            f"{_awal_bahan(riset, bahan)}{_perintah_inti(inti)}"
            f"Tulis naskah voice-over sekitar {kata} kata (±{lebih}), JANGAN lebih dari {kata + lebih} kata karena "
            f"videonya hanya {durasi} detik.{ringkas} "
            f"{g['pendek'] if durasi <= 90 else g['panjang']}{_perintah_cta(cta)}")},
    ]
    teks = ollama.chat(cfg, pesan, suhu=0.8, batal=batal, saat_token=saat_token, maks_token=int(kata * 3 + 200))
    teks = buang_fakta_berulang(bersihkan(teks))
    if gaya in GAYA_FAKTA:
        teks = periksa_fakta(cfg, teks, riset, batal, log)[0]
    return teks, []


SCHEMA_KERANGKA = {
    "type": "object",
    "properties": {"bagian": {"type": "array", "items": {
        "type": "object", "properties": {"judul": {"type": "string"}, "isi": {"type": "string"}},
        "required": ["judul", "isi"]}}},
    "required": ["bagian"],
}


BAGIAN_PANJANG = {  # instruksi bagian pertama/terakhir kerangka & naskah panjang per gaya
    "sains": {
        "kerangka_awal": "berupa dua kalimat (fakta paling mengejutkan + kontras \"tapi…\"), janji jawaban, ",
        "tengah": ("tiap bagian menjawab SATU pertanyaan BARU (penyebabnya, cara kerjanya, buktinya, sejarah "
                   "penemuannya, dampaknya bagi manusia) dengan fakta konkret dari BAHAN FAKTA, analogi sehari-hari, "
                   "dan pembanding skala; urut dari yang mengejutkan ke yang paling mengejutkan, tidak ada fakta yang "
                   "dibahas di dua bagian"),
        "kerangka_akhir": ("Bagian terakhir: jawaban paling mengejutkan yang menjawab hook di awal, dampaknya bagi kita, "
                           "dan penutup — BUKAN rangkuman."),
        "pertama": ("Ini bagian PERTAMA: dua kalimat pertama adalah hook (fakta paling mengejutkan, lalu kontras "
                    "\"tapi…\"; masing-masing maksimal 14 kata), lalu satu kalimat janji apa yang akan terjawab, lalu "
                    "kenapa itu aneh dengan minimal satu fakta konkret (angka, nama, atau tempat) dari BAHAN FAKTA. "
                    "Tanpa pengantar, definisi panjang, atau sapaan. Jangan mengulang pertanyaan hook dengan kata lain "
                    "dan jangan kalimat pengantar kosong seperti \"Keanehan ini membawa kita pada…\" atau \"Kita perlu "
                    "melihat lebih dalam…\"."),
        "porsi_awal": 0.55,
        "terakhir": ("Ini bagian TERAKHIR: JANGAN merangkum dan JANGAN mengulang fakta atau angka yang sudah disebut. "
                     "Ungkap jawaban yang menjawab hook di awal video, satu kalimat dampaknya yang bikin wow (boleh "
                     "sedikit jenaka), lalu satu pertanyaan ke penonton."),
    },
    "meyakinkan": {
        "kerangka_awal": "berupa hal yang pernah didengar penonton lalu dibelokkan, plus jawaban untuk skeptisnya penonton ",
        "tengah": ("rekam jejak berurutan dari fakta nyata (tiap bagian satu periode atau satu temuan konkret dari BAHAN "
                   "FAKTA, dengan tahun dan nama), lalu titik-titik yang disambungkan, pola besarnya, siapa yang "
                   "diuntungkan, dan kenapa ini penting buat penonton"),
        "kerangka_akhir": ("Bagian terakhir: rangkuman titik-titiknya, versi resmi singkat secara adil, sikap pribadi "
                           "\"bisa jadi aku salah\", dan penutup."),
        "pertama": ("Ini bagian PERTAMA: buka dengan hal yang pasti pernah didengar penonton lalu belokkan (\"tapi yang "
                    "mau aku tunjukin bukan teori, ini yang tercatat\"), lalu jawab skeptisnya penonton."),
        "porsi_awal": 0.55,
        "terakhir": ("Ini bagian TERAKHIR: rangkum titik-titik yang sudah disambungkan dalam beberapa kalimat pendek, "
                     "sebut versi resmi singkat secara adil, lalu sikap pribadi \"ini kacamata aku, bisa jadi aku salah, "
                     "tapi semua tadi tercatat\", lalu satu pertanyaan ke penonton."),
    },
    "twist": {
        "kerangka_awal": "berupa kecurigaan terbesar (sebagai klaim) plus perbandingan visual yang mengejutkan ",
        "kerangka_akhir": ("Bagian terakhir: twist berupa kemungkinan jalan tengah yang mengejutkan (sebagai teori), "
                           "satu dua kalimat fakta yang terbukti, dan penutup."),
        "pertama": "Ini bagian PERTAMA: langsung lempar kecurigaan terbesar sebagai klaim dan bandingkan secara visual, "
                   "jangan menjelaskan versi resmi.",
        "porsi_awal": 0.55,
        "terakhir": "Ini bagian TERAKHIR: berikan twist berupa kemungkinan jalan tengah yang mengejutkan (tetap dengan "
                    "penanda klaim), lalu satu dua kalimat fakta yang sudah terbukti tanpa menggurui, lalu tutup dengan "
                    "satu pertanyaan ke penonton.",
    },
    "bangun_teori": {
        "kerangka_awal": "berupa pertanyaan besar plus latar legenda/cerita kunonya ",
        "tengah": ("tiap bagian membahas SATU bukti (benda, situs, temuan, laporan, atau legenda): semua bukti di catatan "
                   "pembuat video ditambah bukti lain dari BAHAN FAKTA, ditambah satu bagian tentang proses ilmiah yang "
                   "dipakai teori ini"),
        "kerangka_akhir": ("Bagian terakhir: rangkuman teori besarnya, satu kalimat jujur bahwa belum ada bukti ilmiah "
                           "yang memastikannya, dan penutup."),
        "pertama": "Ini bagian PERTAMA: buka dengan pertanyaan besar yang bikin penasaran, lalu latar legendanya.",
        "terakhir": "Ini bagian TERAKHIR: rangkum teori besarnya dengan dramatis, lalu satu kalimat jujur bahwa sampai "
                    "sekarang belum ada bukti ilmiah yang memastikannya sehingga kita tidak pernah tahu pasti, lalu "
                    "satu pertanyaan ke penonton.",
    },
    "edukasi": {
        "kerangka_awal": "berupa pertanyaan yang bikin penasaran plus latar singkat yang dibutuhkan supaya paham ",
        "tengah": ("tiap bagian membahas SATU hal dari daftar di catatan pembuat video (urut sesuai catatan): ciri yang "
                   "bisa dilihat, tebakan, jawaban yang benar, dan bukti konkretnya; mitos yang populer diluruskan di "
                   "bagian yang relevan"),
        "kerangka_akhir": "Bagian terakhir: kesimpulan besar yang mengikat semuanya dan penutup.",
        "pertama": "Ini bagian PERTAMA: buka dengan pertanyaan yang bikin penasaran, lalu latar singkat yang "
                   "dibutuhkan supaya paham.",
        "terakhir": "Ini bagian TERAKHIR: kesimpulan besar yang mengikat semuanya dengan bahasa santai, lalu satu "
                    "pertanyaan ke penonton.",
    },
    "seimbang": {
        "kerangka_awal": "",
        "kerangka_akhir": "Bagian terakhir: penjelasan resmi/ilmiah dan penutup.",
        "pertama": "Ini bagian PERTAMA: mulai dengan hook pendek yang bikin penasaran, lalu kenalkan topiknya.",
        "terakhir": "Ini bagian TERAKHIR: sampaikan penjelasan resmi/ilmiah secara adil, lalu tutup video dengan satu "
                    "pertanyaan ke penonton.",
    },
}


def _daftar_bukti(riset):
    """Ceklis untuk kerangka "bangun teori": bukti dari catatan pengguna + semua artikel bukti hasil riset."""
    judul = [s["judul"] for s in riset if s.get("terkait")]
    return ("\nWAJIB: SEMUA bukti yang disebut di catatan pembuat video masuk ke kerangka (sebut namanya di isi "
            "bagian), lalu bukti dari artikel BAHAN FAKTA berikut juga dipakai sebanyak mungkin: "
            + ", ".join(judul) + ". Satu bagian tengah membahas satu bukti; kalau buktinya lebih banyak dari bagian, "
            "satu bagian boleh membahas dua bukti yang mirip." if judul else
            "\nWAJIB: SEMUA bukti yang disebut di catatan pembuat video masuk ke kerangka.")


def _tulis_panjang(cfg, bahan, riset, durasi, batal, saat_token, log, gaya="twist", cta="", inti=""):
    """Model 12B lokal mudah mengulang/ngelantur kalau disuruh menulis 1000+ kata sekaligus.
    Jadi: buat kerangka dulu, lalu tulis tiap bagian. Awal prompt dibuat identik di setiap panggilan supaya
    Ollama bisa memakai ulang cache-nya (bahan riset yang panjang tidak dibaca ulang dari nol).
    inti = rencana garis cerita (inti_cerita): ikut di awal prompt supaya semua bagian menuju jawaban yang sama."""
    total = target_kata(durasi)
    # "Bangun teori" butuh satu bagian per bukti: 4 bagian untuk 5 menit membuat bukti-bukti dari catatan
    # pengguna (kapak, pedang) terbuang karena bagian tengahnya cuma dua.
    n = max(5, min(16, round(durasi / 45))) if gaya in ("bangun_teori", "edukasi") else \
        max(4, min(14, round(durasi / 80)))
    per_bagian = int(total / n * 1.15)  # model cenderung menulis ±15% lebih pendek dari yang diminta
    dasar = f"{_awal_bahan(riset, bahan)}{_perintah_inti(inti)}"
    schema = json.loads(json.dumps(SCHEMA_KERANGKA))
    schema["properties"]["bagian"].update(minItems=n, maxItems=n)
    log(f"Video panjang ({durasi // 60} menit): AI menyusun kerangka {n} bagian…")
    SIS = sistem(gaya)
    seru = gaya != "seimbang"
    bp = BAGIAN_PANJANG.get(gaya, BAGIAN_PANJANG["twist"])
    kerangka = ollama.chat_json(cfg, [{"role": "system", "content": SIS}, {"role": "user", "content": (
        dasar + f"Susun KERANGKA video {durasi // 60} menit dengan tepat {n} bagian. Bagian pertama: hook "
        + bp["kerangka_awal"] + "dan pengenalan topik. Bagian tengah: "
        + bp.get("tengah", "latar belakang, isi teori, \"bukti\" yang diajukan orang-orang yang percaya, fakta nyata yang jarang "
                 "diketahui, kejanggalan, tokoh/peristiwa penting") + (", dengan ketegangan yang terus naik" if seru else "") + ". "
        + bp["kerangka_akhir"] + " Tiap bagian: "
        "judul (2-5 kata, untuk chapter YouTube) dan isi (1-2 kalimat tentang apa yang dibahas, dengan fakta "
        "konkret dari BAHAN FAKTA). Jangan ada dua bagian yang membahas hal sama."
        + (_daftar_bukti(riset) if gaya == "bangun_teori" else "")
        + ("\nWAJIB: SEMUA hal di daftar catatan pembuat video masuk ke kerangka, masing-masing satu bagian tengah."
           if gaya == "edukasi" else ""))}],
        schema, batal=batal, maks_token=90 * n + 200)
    bagian = [b for b in kerangka.get("bagian", []) if b.get("judul")][:n]
    if len(bagian) < 3:
        raise RuntimeError("AI gagal menyusun kerangka naskah, coba lagi")
    daftar = "\n".join(f"{i + 1}. {b['judul']}: {b['isi']}" for i, b in enumerate(bagian))
    log("Kerangka: " + " | ".join(b["judul"] for b in bagian))

    hasil, bab = [], []
    for i, b in enumerate(bagian):
        if batal:
            batal.cek()
        if i == 0:
            posisi = bp["pertama"]
        elif i == len(bagian) - 1:
            posisi = bp["terakhir"] + _perintah_cta(cta)
        else:
            posisi = ("Ini bagian TENGAH: jangan membuka dengan hook atau sapaan baru, jangan menutup video, "
                      "jangan bertanya ke penonton. Kalimat pertama langsung hal baru yang menarik, bukan pengantar; "
                      "jangan mengulang fakta atau angka dari bagian sebelumnya."
                      + (" Akhiri bagian ini dengan kalimat penggantung yang bikin penasaran ke bagian berikutnya."
                         if seru else ""))
        sambung = f"\nBagian sebelumnya berakhir dengan: «{' '.join(hasil[-1].split()[-60:])}»\n" \
                  "Lanjutkan dengan mulus tanpa mengulang isi sebelumnya." if hasil else ""
        sudah = sum(len(h.split()) for h in hasil)
        # Dengan aturan "padat" model menulis ±125 kata walau diminta 190 (Komodo: 497 dari 660 kata, video 5 menit
        # jadi 3:18): kekurangan bagian sebelumnya dibagi ke bagian yang tersisa.
        minta = min(int(per_bagian * 1.6), max(per_bagian, int((total - sudah) / (len(bagian) - i) * 1.15)))
        if i == 0 and bp.get("porsi_awal"):
            # Isi bagian pertama gaya ber-hook cuma hook, janji, dan kenapa aneh: dengan jatah penuh (±190 kata) model
            # mengisinya dengan pertanyaan hook yang diulang-ulang (Mariana: ±50 detik tanpa fakta). Sisanya otomatis
            # dibagi ke bagian berikutnya lewat rumus di atas.
            minta = int(per_bagian * bp["porsi_awal"])

        def token(teks, sudah=sudah):
            if saat_token:
                saat_token(teks, sudah, total, f"bagian {i + 1}/{len(bagian)}")

        teks = ollama.chat(cfg, [{"role": "system", "content": SIS}, {"role": "user", "content": (
            dasar + f"KERANGKA VIDEO:\n{daftar}\n\n"
            f"Sekarang tulis HANYA bagian {i + 1}: \"{b['judul']}\" — {b['isi']}\n"
            f"Panjang sekitar {minta} kata. {posisi}{sambung}\n"
            "Jangan menulis judul bagian. Aturan hook dan pertanyaan penutup hanya berlaku untuk bagian pertama "
            "dan terakhir.")}], suhu=0.8, batal=batal, saat_token=token, maks_token=int(minta * 3 + 150))
        teks = bersihkan(teks)
        if teks and hasil:
            hasil[-1], teks = _buang_ulangan(hasil[-1], teks)
        if teks:
            hasil.append(teks)
            bab.append({"judul": b["judul"].strip()[:60], "awal": " ".join(teks.split()[:8]),
                        "kalimat": pecah_kalimat(teks)[:4]})
    naskah_jadi = buang_fakta_berulang("\n\n".join(hasil))
    if len(naskah_jadi.split()) < 0.95 * sum(len(h.split()) for h in hasil):
        log(f"Kalimat yang mengulang fakta dibuang: {sum(len(h.split()) for h in hasil)} → "
            f"{len(naskah_jadi.split())} kata")
    ganti = {}
    if gaya in GAYA_FAKTA:
        naskah_jadi, ganti = periksa_fakta(cfg, naskah_jadi, riset, batal, log)
    # awal bab harus tetap ada di naskah (chapter YouTube dicari dari 8 kata pertamanya): kalimat pembuka yang dibuang
    # atau diperbaiki diganti kalimat bab itu berikutnya yang masih ada
    rata = " ".join(naskah_jadi.split())
    for b in bab:
        for k in b.pop("kalimat"):
            awal = " ".join(ganti.get(k, k).split()[:8])
            if awal and awal in rata:
                b["awal"] = awal
                break
    bab = [b for b in bab if b["awal"] in rata]
    return naskah_jadi, bab


def ringkas_shorts(cfg, naskah_panjang, batal=None, saat_token=None, gaya="twist", cta=""):
    """Versi Shorts ±1 menit dari naskah video panjang (untuk format "keduanya")."""
    kata = target_kata(60)
    inti = {"meyakinkan": "hook yang dibelokkan, dua fakta nyata paling kuat yang disambungkan jadi pertanyaan "
                          "\"kebetulan?\", dan sikap \"bisa jadi aku salah\"",
            "sains": "fakta paling mengejutkan, jawaban para ilmuwan dengan satu analogi, dan satu angka pembanding",
            "twist": "hook paling mengejutkan, petunjuk paling menarik, dan twist-nya (tetap sebagai teori) plus satu "
                     "kalimat fakta",
            "bangun_teori": "pertanyaan besarnya, dua atau tiga bukti paling mengejutkan, dan kalimat jujur bahwa "
                            "belum terbukti",
            "edukasi": "pertanyaan pembukanya, dua atau tiga jawaban paling mengejutkan beserta buktinya, dan satu mitos "
                       "yang diluruskan",
            }.get(gaya, "hook paling kuat, satu atau dua kejanggalan paling menarik, dan penjelasan resmi singkat")
    pesan = [{"role": "system", "content": sistem(gaya)}, {"role": "user", "content": (
        f"Ini naskah video YouTube panjang:\n\n{naskah_panjang[:12000]}\n\n"
        f"Buat versi Shorts sekitar {kata} kata dari naskah itu. Ambil {inti}. "
        "Semua fakta HANYA dari naskah di atas. Sebelum pertanyaan "
        "penutup, tulis satu kalimat bahwa cerita lengkapnya ada di video panjang di channel ini."
        + _perintah_cta(cta))}]
    teks = ollama.chat(cfg, pesan, suhu=0.7, batal=batal, saat_token=saat_token, maks_token=int(kata * 3 + 200))
    return bersihkan(teks)


def rencana_reels(cfg, naskah_panjang, jumlah, batal=None, log=print):
    """Fokus berbeda untuk tiap reels teaser dari satu video panjang (satu bukti/kejanggalan/pertanyaan per reels)."""
    kolom = [f"fokus_reels_{i}" for i in range(1, jumlah + 1)]  # kolom datar: array membuat gemma mengulang token
    schema = {"type": "object", "properties": {k: {"type": "string"} for k in kolom}, "required": kolom}
    pesan = [{"role": "user", "content": (
        f"Ini naskah video YouTube panjang:\n\n{naskah_panjang[:12000]}\n\n"
        f"Dari naskah itu akan dibuat {jumlah} reels pendek yang memancing orang menonton video panjangnya. "
        f"Tentukan fokus tiap reels: {jumlah} bagian BERBEDA yang paling bikin penasaran (misalnya satu fakta "
        "atau bukti tertentu, satu keanehan, satu perbandingan yang mengejutkan, atau pertanyaan besarnya). Jangan ada "
        "dua reels dengan fokus yang sama. Urutkan dari yang paling menarik.\n"
        "Tiap fokus: satu kalimat bahasa Indonesia yang menyebut bagian naskahnya secara spesifik (nama benda, "
        "tempat, atau kejadiannya).")}]
    try:
        j = ollama.chat_json(cfg, pesan, schema, batal=batal, maks_token=90 * jumlah + 60, suhu=0.5)
        fokus = [" ".join(str(j.get(k) or "").split())[:300] for k in kolom]
    except (RuntimeError, ValueError) as e:
        log(f"Rencana reels gagal ({e}) — fokus diambil dari bagian-bagian naskah")
        fokus = [""] * jumlah
    # Cadangan: kalimat pembuka dari bagian naskah yang berbeda-beda.
    paragraf = [x for x in naskah_panjang.split("\n\n") if len(x.split()) > 8] or [naskah_panjang]
    for i, f in enumerate(fokus):
        if not f:
            bagian = paragraf[min(len(paragraf) - 1, i * len(paragraf) // jumlah)]
            fokus[i] = pecah_kalimat(bagian)[0][:300]
    return fokus


def teaser(cfg, naskah_panjang, fokus, durasi, batal=None, saat_token=None, cta="", gaya=""):
    """Naskah reels teaser: bukan ringkasan, tapi pancingan yang berhenti di titik paling penasaran.
    Channel fakta (gaya sains/edukasi): penonton tetap mendapat satu fakta "wow" yang utuh supaya betah sampai akhir
    — teaser yang cuma menggantung ("Tapi yang ditemukan berikutnya justru lebih aneh.") terasa kosong."""
    kata = target_kata(durasi)
    if gaya in GAYA_FAKTA:
        aturan = f"""- Ini REELS untuk memancing penonton menonton video panjangnya, tapi penonton harus tetap mendapat satu hal "wow" yang utuh.
- Fokus HANYA pada bagian ini: {fokus}
- Kalimat pertama (maksimal 12 kata): fakta paling mengejutkan dari fokus itu yang bisa langsung dibayangkan, pakai angka atau perbandingan. Bukan "banyak yang yakin", bukan "tahukah kamu", bukan pengantar.
- Kalimat kedua: kontras "tapi…" yang bikin penasaran.
- Lalu dua atau tiga detail yang makin lama makin mengejutkan, kalimat pendek dan padat, tiap fakta disebut sekali saja.
- Ungkap satu jawaban atau fakta "wow" sampai tuntas, lalu tutup dengan SATU pertanyaan lebih besar yang jawabannya ada di video panjang (polanya seperti "Lalu kenapa akarnya tidak pernah mati? Jawabannya ada di video lengkapnya." — dengan kata-katamu sendiri dari topik ini).
- Semua nama, angka, dan fakta HANYA dari naskah video panjang di bawah. Jangan menambah fakta baru."""
        sis = f"{_PERAN_FAKTA}\nGayamu: narator reels sains yang padat dan seru, bikin orang menonton sampai detik terakhir."
    else:
        aturan = f"""- Ini REELS TEASER untuk memancing penonton menonton video panjangnya, BUKAN ringkasan.
- Fokus HANYA pada bagian ini: {fokus}
- Kalimat pertama (maksimal 12 kata) langsung hook paling bikin penasaran dari fokus itu: pertanyaan atau klaim mengejutkan (klaim tetap diberi penanda seperti "katanya" atau "banyak yang yakin").
- Sebut satu sampai tiga detail paling aneh atau mengejutkan dari fokus itu, bangun ketegangan, lempar pertanyaan.
- JANGAN bongkar jawaban, twist, kesimpulan, atau penjelasan resminya. Berhenti di titik paling penasaran, misalnya "Tapi yang ditemukan berikutnya justru lebih aneh."
- Semua nama, angka, dan fakta HANYA dari naskah video panjang di bawah. Jangan menambah fakta baru."""
        sis = f"{_PERAN}\nGayamu: narator teaser misteri yang membuat orang tidak bisa berhenti penasaran."
    pesan = [{"role": "system", "content": (
        f"{sis}\n\nATURAN:\n{aturan}\n{_ATURAN_UMUM}")}, {"role": "user", "content": (
        f"NASKAH VIDEO PANJANG:\n{naskah_panjang[:12000]}\n\n"
        f"Tulis naskah reels teaser sekitar {kata} kata dengan fokus: {fokus}"
        + (f"\nKalimat paling akhir persis ajakan ini: «{cta}»" if cta else ""))}]
    teks = ollama.chat(cfg, pesan, suhu=0.75, batal=batal, saat_token=saat_token, maks_token=int(kata * 3 + 200))
    return buang_fakta_berulang(bersihkan(teks))


def short_dari_sumber(cfg, transkrip, tema, durasi, gaya_short="teaser", batal=None, saat_token=None, cta=""):
    """Mode Re-create: naskah short BARU (ditulis ulang, bukan dipotong) dari transkrip video panjang, sesuai tema.
    gaya_short "teaser" = bikin penasaran lalu ajak menonton video panjangnya; "mandiri" = cerita pendek utuh."""
    if gaya_short == "teaser":
        return teaser(cfg, transkrip, tema, durasi, batal, saat_token, cta=cta)
    kata = target_kata(durasi)
    aturan = f"""- Ini SHORT mandiri yang ditulis ulang dari video panjang, fokus HANYA pada tema: {tema}
- Jangan menyalin kalimat dari transkrip; tulis ulang dengan kalimat baru yang lebih padat dan seru.
- Kalimat pertama (maksimal 12 kata) adalah hook paling bikin penasaran tentang tema itu.
- Lalu dua sampai empat poin paling menarik tentang tema itu, berurutan dan mudah diikuti, dengan ketegangan naik.
- Klaim dan teori tetap diberi penanda ("katanya", "banyak yang yakin", "menurut teori ini").
- Tutup dengan satu pertanyaan ke penonton.
- Semua nama, angka, dan fakta HANYA dari transkrip di bawah. Jangan menambah fakta baru."""
    pesan = [{"role": "system", "content": (
        f"{_PERAN}\nGayamu: narator short misteri yang padat, dramatis, dan bikin orang menonton sampai habis."
        f"\n\nATURAN:\n{aturan}\n{_ATURAN_UMUM}")}, {"role": "user", "content": (
        f"TRANSKRIP VIDEO PANJANG:\n{transkrip[:12000]}\n\n"
        f"Tulis naskah short sekitar {kata} kata dengan tema: {tema}"
        + (f"\nSetelah pertanyaan penutup, kalimat paling akhir persis ajakan ini: «{cta}»" if cta else ""))}]
    teks = ollama.chat(cfg, pesan, suhu=0.75, batal=batal, saat_token=saat_token, maks_token=int(kata * 3 + 200))
    return bersihkan(teks)


SCHEMA_META = {
    "type": "object",
    "properties": {
        "judul": {"type": "string"},
        "deskripsi": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 8, "maxItems": 12},
        "teks_thumbnail": {"type": "string"},
    },
    "required": ["judul", "deskripsi", "tags", "teks_thumbnail"],
}


def _potong_judul(teks, maks=70):
    teks = " ".join(teks.split()).rstrip("?.!")
    if len(teks) <= maks:
        return teks
    return teks[:maks].rsplit(" ", 1)[0] + "…"


def meta(cfg, naskah, format_video, batal=None, log=print, gaya=""):
    fakta = gaya in GAYA_FAKTA
    pesan = [{"role": "user", "content": (
        f"Ini naskah video {'sains/fakta' if fakta else 'misteri/teori konspirasi'}:\n\n" + naskah[:5000] + "\n\n"
        "Buat untuk upload:\n"
        "- judul: maksimal 70 karakter, bikin penasaran tapi jujur (jangan klaim \"TERBUKTI\" atau \"100% NYATA\").\n"
        + ("- deskripsi: 2-3 kalimat ringkas isi video dan apa yang akan penonton ketahui.\n" if fakta else
           "- deskripsi: 2-3 kalimat ringkas isi video, sebut bahwa ini membahas teori, bukan fakta yang sudah terbukti.\n")
        + "- tags: 8-12 kata kunci/hashtag tanpa tanda #, campur bahasa Indonesia dan Inggris.\n"
        "- teks_thumbnail: 2-4 kata HURUF BESAR untuk ditempel di thumbnail.")}]
    m = {}
    for coba in range(3):  # model kecil kadang memotong JSON di tengah; ulangi dengan suhu sedikit lebih tinggi
        try:
            m = ollama.chat_json(cfg, pesan, SCHEMA_META, batal=batal, maks_token=800, suhu=0.3 + coba * 0.2)
            if m.get("judul"):
                break
        except (RuntimeError, ValueError) as e:
            log(f"Judul/tag gagal dibuat (percobaan {coba + 1}): {e}")
    judul = m.get("judul") or _potong_judul(re.split(r"(?<=[.!?])\s", naskah.strip())[0])
    judul = judul.strip()[:100]
    tags, lihat = [], set()
    for t in m.get("tags") or []:
        t = re.sub(r"^#", "", str(t)).strip()
        # Buang tag rusak dari model kecil, misal "t_u_f_o", "luar_angka", "mil947".
        if (not t or "_" in t or len(t) > 30 or re.search(r"[a-z][0-9]|[0-9][a-z]", t.lower())
                or any(len(w) == 1 for w in t.split()) or t.lower() in lihat):
            continue
        lihat.add(t.lower())
        tags.append(t)
    tags = tags[:15]
    if format_video == "9:16" and "shorts" not in [t.lower() for t in tags]:
        tags.append("shorts")
    return {"judul": judul, "deskripsi": (m.get("deskripsi") or "").strip(), "tags": tags,
            "teks_thumbnail": (m.get("teks_thumbnail") or "").strip().upper()[:40]}


def pecah_kalimat(teks):
    teks = re.sub(r"\s+", " ", teks.replace("\n", " ")).strip()
    bagian = re.split(r"(?<=[.!?…])\s+(?=[\"“A-Z0-9])", teks)
    return [b.strip() for b in bagian if b.strip()]


def pecah_adegan(naskah, format_video):
    """Adegan = 1 atau beberapa kalimat. Shorts dipotong lebih rapat supaya visual cepat berganti."""
    minim, target, maks = (5, 12, 20) if format_video == "9:16" else (10, 26, 40)
    potongan = []
    for k in pecah_kalimat(naskah):
        if len(k.split()) <= maks:
            potongan.append(k)
            continue
        sisa = ""
        for frasa in re.split(r"(?<=[,;:])\s+", k):
            if sisa and len((sisa + " " + frasa).split()) > maks:
                potongan.append(sisa)
                sisa = frasa
            else:
                sisa = (sisa + " " + frasa).strip()
        if sisa:
            potongan.append(sisa)
    adegan, kumpul = [], ""
    for p in potongan:
        if kumpul and (len(kumpul.split()) >= target or len((kumpul + " " + p).split()) > maks):
            adegan.append(kumpul)
            kumpul = p
        else:
            kumpul = (kumpul + " " + p).strip()
    if kumpul:
        if adegan and len(kumpul.split()) < minim:
            adegan[-1] += " " + kumpul
        else:
            adegan.append(kumpul)
    return adegan


SCHEMA_CARI = {
    "type": "object",
    "properties": {
        "adegan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"no": {"type": "integer"}, "a": {"type": "string"}, "b": {"type": "string"},
                               "c": {"type": "string"}, "lihat": {"type": "string"}, "subjek": {"type": "string"},
                               "teks_layar": {"type": "string"}, "analogi": {"type": "string"},
                               "jumlah": {"type": "integer"}, "latar": {"type": "string"}},
                "required": ["no", "a", "b", "c", "lihat", "subjek", "teks_layar", "analogi", "jumlah", "latar"],
            },
        }
    },
    "required": ["adegan"],
}

def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


SCHEMA_BANDING = {  # kolom datar (bukan array): skema array membuat gemma mengulang token
    "type": "object",
    "properties": {"ada": {"type": "boolean"}, "no": {"type": "integer"},
                   "kueri_kiri": {"type": "string"}, "label_kiri": {"type": "string"},
                   "lihat_kiri": {"type": "string"},
                   "kueri_kanan": {"type": "string"}, "label_kanan": {"type": "string"},
                   "lihat_kanan": {"type": "string"},
                   "satu_foto": {"type": "boolean"},
                   "dunia_kiri": {"type": "string", "enum": ["asli", "bulan", "bumi", "mars", "malam", "kuno"]},
                   "dunia_kanan": {"type": "string", "enum": ["asli", "bulan", "bumi", "mars", "malam", "kuno"]}},
    "required": ["ada", "no", "kueri_kiri", "label_kiri", "lihat_kiri", "kueri_kanan", "label_kanan", "lihat_kanan",
                 "satu_foto", "dunia_kiri", "dunia_kanan"],
}


def cari_perbandingan(cfg, judul, adegan, batal=None, log=print, sumber=()):
    """Satu adegan yang ditampilkan sebagai PERBANDINGAN dua gambar berdampingan (misalnya foto pendaratan
    di Bulan vs tempat mirip di Bumi). sumber = judul artikel riset (nama tempat/benda nyata untuk dibandingkan).
    Mengembalikan dict atau None."""
    daftar = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(adegan))
    pesan = [{"role": "user", "content": (
        f"Video tentang: {judul}\n\nADEGAN:\n{daftar}\n\n"
        + (f"Artikel riset yang tersedia (nama tempat/benda nyata): {', '.join(sumber)}\n\n" if sumber else "")
        + "Pilih SATU adegan yang paling kuat kalau ditampilkan sebagai PERBANDINGAN DUA FOTO berdampingan, "
        "sebaiknya adegan yang memang membandingkan atau menyebut kemiripan (misalnya foto pendaratan di Bulan "
        "vs tempat di Bumi yang mirip; foto Nessie vs hewan nyata; Gunung Padang vs piramida Mesir).\n"
        "- no: nomor adegannya.\n"
        "Kedua foto harus SEJENIS dan tampak mirip kalau dijajarkan (sama-sama pemandangan, sama-sama benda, "
        "atau sama-sama makhluk), bukan foto orang yang sedang bekerja atau peta/diagram.\n"
        "- kueri_kiri / kueri_kanan: kata kunci pencarian foto dalam bahasa Inggris, 2-5 kata, objek/tempat "
        "NYATA yang spesifik dengan namanya (misalnya \"Buzz Aldrin Apollo 11 surface\", \"Iceland lava field\", "
        "\"Cinder Lake crater field\"), bukan istilah umum seperti \"training site\".\n"
        "- lihat_kiri / lihat_kanan: apa yang HARUS terlihat di foto itu, bahasa Indonesia maksimal 12 kata "
        "(misalnya \"astronot berdiri di permukaan Bulan abu-abu berdebu\", \"padang lava abu-abu tandus tanpa "
        "tumbuhan\").\n"
        "- label_kiri / label_kanan: teks pendek HURUF BESAR maksimal 22 huruf untuk ditempel di foto (misalnya "
        "\"BULAN, 1969\", \"ISLANDIA, BUMI\"). Label menyebut tempat/benda yang SAMA dengan kuerinya — jangan "
        "menulis lokasi lain (kueri \"Transantarctic Mountains\" tidak boleh berlabel \"ARKTIK\").\n"
        "- satu_foto: true kalau yang dibandingkan adalah LOKASI PENGAMBILAN foto yang sama (misalnya \"foto "
        "pendaratan ini sebenarnya diambil di Bumi?\"). Maka dipakai SATU foto yang sama dalam dua versi: daratannya "
        "sama persis, latar dan warnanya beda — jauh lebih meyakinkan daripada dua foto berbeda. kueri_kiri/lihat_kiri "
        "= foto aslinya (harus memperlihatkan daratan DAN langit/cakrawala), dunia_kiri = dunia asli foto itu "
        "(atau \"asli\"), dunia_kanan = dunia pembandingnya. Pilihan dunia: \"bulan\" (abu-abu, langit hitam), "
        "\"bumi\" (berwarna, langit biru), \"mars\" (tanah merah, langit jingga), \"malam\" (gelap, langit "
        "berbintang), \"kuno\" (foto tua sepia), \"asli\" (apa adanya). Contoh: foto pendaratan Bulan → bulan vs "
        "bumi; foto permukaan Mars yang katanya diambil di gurun → mars vs bumi; foto UFO siang hari yang katanya "
        "palsu → asli vs malam. false untuk membandingkan dua benda/tempat yang berbeda (Nessie vs fosil, Gunung "
        "Padang vs piramida); dunia_kiri dan dunia_kanan lalu diisi \"asli\".\n"
        "Kalau tidak ada adegan yang cocok untuk dibandingkan, isi ada=false.")}]
    try:
        j = ollama.chat_json(cfg, pesan, SCHEMA_BANDING, batal=batal, maks_token=320, suhu=0.3)
    except (RuntimeError, ValueError) as e:
        log(f"Perbandingan visual gagal dipilih ({e})")
        return None
    no = _int(j.get("no"))
    if not j.get("ada") or not (1 <= no <= len(adegan)) or not j.get("kueri_kiri") or not j.get("kueri_kanan"):
        return None
    hasil = {"no": no}
    for sisi in ("kiri", "kanan"):
        hasil[sisi] = {"kueri": str(j[f"kueri_{sisi}"]).strip()[:60],
                       "label": str(j.get(f"label_{sisi}") or "").strip().upper()[:24],
                       "lihat": str(j.get(f"lihat_{sisi}") or "").strip()[:120]}
    sama = lambda x: " ".join(re.findall(r"\w+", x.lower()))
    dunia = (j.get("dunia_kiri"), j.get("dunia_kanan"))
    # Gemma sering tetap memilih dua foto berbeda untuk "foto Bulan vs lokasi latihan di Bumi". Pengguna minta untuk
    # kasus lokasi syuting dipakai SATU foto yang sama dalam dua dunia, jadi aturan ini dipaksa.
    kiri_teks = f"{hasil['kiri']['kueri']} {hasil['kiri']['label']} {hasil['kiri']['lihat']}".lower()
    kanan_teks = f"{hasil['kanan']['kueri']} {hasil['kanan']['label']} {hasil['kanan']['lihat']}".lower()
    luar = "mars" if re.search(r"\bmars\b", kiri_teks) else "bulan" if re.search(r"bulan|moon|lunar|apollo", kiri_teks) else ""
    if not j.get("satu_foto") and luar and re.search(
            r"bumi|earth|gurun|desert|nevada|arizona|islandia|iceland|studio|latihan|training|lokasi|syuting|"
            r"cinder|crater field|devon", kanan_teks):
        j["satu_foto"], dunia = True, (luar, "bumi")
        hasil["kanan"]["label"] = "KALAU DI BUMI?"
    if dunia[1] == "asli" and dunia[0] not in (None, "asli"):  # sisi olahan selalu di kanan
        dunia = (dunia[1], dunia[0])
        hasil["kiri"]["label"], hasil["kanan"]["label"] = hasil["kanan"]["label"], hasil["kiri"]["label"]
    if j.get("satu_foto") and dunia[0] != dunia[1] and dunia[1] not in (None, "asli"):
        # satu foto, dua dunia: sisi kanan hasil olahan, jadi labelnya wajib menyebut ILUSTRASI (jujur ke penonton)
        hasil["mode"] = "satu_foto"
        hasil["kiri"]["dunia"], hasil["kanan"]["dunia"] = dunia
        hasil["kanan"].update(kueri=hasil["kiri"]["kueri"], lihat=hasil["kiri"]["lihat"])
        if "ILUSTRASI" not in hasil["kanan"]["label"]:
            dasar = hasil["kanan"]["label"]
            if len(dasar) > 16:  # potong di batas kata, bukan di tengah kata ("KALAU DI BUM")
                dasar = dasar[:16].rsplit(" ", 1)[0]
            hasil["kanan"]["label"] = f"{dasar.rstrip(' ,')} (ILUSTRASI)".strip()
        if sama(hasil["kiri"]["label"]) == sama(hasil["kanan"]["label"]):
            return None
        log(f"Perbandingan 🆚 satu foto di adegan {no}: “{hasil['kiri']['label']}” vs “{hasil['kanan']['label']}”")
        return hasil
    if sama(hasil["kiri"]["label"]) == sama(hasil["kanan"]["label"]) or \
            sama(hasil["kiri"]["kueri"]) == sama(hasil["kanan"]["kueri"]):
        # dua sisi berlabel sama ("SLEEPING GIANT, ONTARIO" vs "SLEEPING GIANT, ONTARIO") bukan perbandingan
        log(f"Perbandingan 🆚 dibatalkan: kedua sisi sama (“{hasil['kiri']['label']}”)")
        return None
    log(f"Perbandingan 🆚 di adegan {no}: “{hasil['kiri']['label']}” vs “{hasil['kanan']['label']}”")
    return hasil


CADANGAN = ["dark foggy forest", "night sky stars", "old documents desk", "city at night aerial",
            "man silhouette shadow", "abandoned building", "storm clouds timelapse", "old film projector",
            "typewriter close up", "radar screen"]
# Video fakta/sains: visual dokumenter yang terang (CADANGAN di atas sengaja kelam untuk video misteri).
CADANGAN_CERAH = ["earth from space", "aerial landscape drone", "ocean waves aerial", "forest aerial drone",
                  "starry sky timelapse", "mountains aerial", "scientist laboratory", "desert dunes aerial",
                  "river aerial view", "clouds timelapse"]


def cadangan(fakta=False):
    return CADANGAN_CERAH if fakta else CADANGAN


def kata_kunci_adegan(cfg, judul, adegan, batal=None, log=print, subjek="", artikel=(), fakta=False):
    """subjek = nama topik dalam bahasa Inggris (judul artikel Wikipedia), misalnya "Loch Ness Monster".
    fakta=True (video sains): visual dokumenter cerah + diagram/peta/citra satelit, bukan suasana kelam/arsip kuno.
    artikel = judul artikel riset lain (bukti/tempat/benda, misalnya "Bixi"): AI menandai adegan mana yang
    membahas artikel itu (kolom "artikel" di hasil), supaya footage-nya diambil dari bukti itu sendiri."""
    artikel = list(artikel)
    hasil = [None] * len(adegan)
    kelompok = 8  # 12 adegan sekaligus terlalu panjang untuk dijawab utuh oleh model 12B di CPU
    for mulai in range(0, len(adegan), kelompok):
        bagian = adegan[mulai:mulai + kelompok]
        daftar = "\n".join(f"{mulai + i + 1}. {t}" for i, t in enumerate(bagian))
        pesan = [{"role": "user", "content": (
            f"Video tentang: {judul}\n"
            + (f"SUBJEK UTAMA: {subjek}. Kalau adegan membahas subjek utama (makhluknya, legendanya, tempatnya, "
               f"kejadiannya), kata kunci a dan c HARUS memuat \"{subjek}\" atau nama spesifik yang berhubungan "
               "langsung dengannya. Jangan memakai kata umum yang bisa berarti hal lain (misalnya \"monk\" untuk "
               "biarawan dalam legenda akan memunculkan foto biksu masa kini; tulis nama tokohnya).\n"
               if subjek else "")
            + ("ARTIKEL BUKTI / HAL TERKAIT:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(artikel)) + "\n"
               "- artikel: nomor artikel di atas yang sedang dibahas adegan itu (adegan lanjutan yang masih membahas "
               "hal yang sama memakai nomor yang sama); 0 kalau adegan membahas subjek utama atau hal umum. Kalau "
               "adegan membahas salah satu artikel itu, kata kunci a dan c memakai nama benda/tempat dari artikel "
               "itu (misalnya \"Bixi stone tortoise\"), BUKAN subjek utama.\n" if artikel else "")
            + "\n"
            "Untuk SETIAP adegan narasi di bawah, tulis 3 kata kunci pencarian footage dalam BAHASA INGGRIS:\n"
            "- a: hal SPESIFIK dan nyata yang disebut (tempat, tokoh, peristiwa, makhluk, benda) untuk dicari di arsip "
            "foto Wikimedia/NASA, 1-4 kata, misalnya \"Area 51\", \"Apollo 11 astronaut\", \"Loch Ness\", "
            "\"Ross Ice Shelf\", \"Richard E. Byrd\". JANGAN satu kata umum yang punya banyak arti (\"Giant\" "
            "memunculkan toko, kolam renang, dan poster film): tambahkan jenisnya, misalnya \"mythological giant "
            "painting\", \"Bixi stone tortoise\". Isi \"\" kalau adegan tidak menyebut hal spesifik.\n"
            "- b: gambaran VISUAL umum yang bisa difilmkan untuk stock video, 2-4 kata, misalnya \"desert night sky\", "
            "\"foggy lake\", \"antarctic ice cliff\", \"dark forest night\". Jangan kata abstrak seperti mystery, "
            "truth, conspiracy, secret. "
            + ("Utamakan visual dokumenter yang jelas dan indah: tambahkan kata seperti aerial, drone, close up, "
               "timelapse, underwater, satellite bila cocok.\n"
               "- c: DIAGRAM, PETA, CITRA SATELIT, atau ILUSTRASI ILMIAH yang cocok, 2-4 kata, misalnya \"Earth mantle "
               "diagram\", \"Nile satellite image\", \"plate tectonics map\", \"Jupiter Hubble image\". Isi \"\" kalau "
               "tidak ada yang cocok.\n" if fakta else
               "Utamakan suasana kelam: tambahkan kata seperti foggy, dark, night, abandoned, silhouette, stormy bila "
               "cocok.\n"
               "- c: ILUSTRASI atau ARSIP LAMA yang cocok (lukisan, ukiran, peta kuno, foto hitam putih), 2-4 kata, "
               "misalnya \"sea serpent engraving\", \"medieval world map\", \"flat earth map\", \"dragon painting\", "
               "\"antarctic expedition 1947\". Isi \"\" kalau tidak ada yang cocok.\n")
            + "- lihat: apa yang HARUS tampak di gambar supaya pas dengan narasi adegan itu, bahasa Indonesia maksimal "
            "12 kata, konkret: benda/tempat/makhluk/peristiwa yang disebut, misalnya \"patung kura-kura batu Bixi "
            "memanggul prasasti\", \"kristal garam Himalaya merah muda\", \"tebing Sleeping Giant di tepi danau\". "
            "Kalau narasinya abstrak (pertanyaan, penghubung, kesimpulan), tulis visual TENTANG TOPIK VIDEO yang ada di "
            "arsip foto/lukisan/ukiran kuno, misalnya \"lukisan kuno raksasa melawan dewa\", \"ukiran raksasa dalam "
            "naskah kuno\" — bukan visual stok umum seperti \"tangan membuka buku\" atau \"peneliti menggali\".\n"
            "- subjek: SUBJEK UTAMA yang sedang dibahas adegan itu, 1-4 kata (benda/makhluk/tempat/tokoh), misalnya "
            "\"raksasa\" untuk \"raksasa yang membatu\", \"patung Bixi\", \"foto pendaratan Apollo 11\". Gambar wajib "
            "menampilkan subjek ini; detail lain (misalnya \"membatu\") hanya pelengkap.\n"
            "- teks_layar: 1-4 kata HURUF BESAR bahasa Indonesia yang ditampilkan besar di layar saat adegan itu: "
            "angka + satuan atau istilah kunci yang DIUCAPKAN di adegan itu, misalnya \"30 JUTA TAHUN\", \"MELEBAR "
            "5 CM\", \"PALUNG MARIANA\". Isi \"\" kalau adegan tidak punya angka atau istilah penting.\n"
            "- analogi: kalau narasi adegan memakai PERBANDINGAN dengan benda sehari-hari supaya penonton bisa "
            "membayangkan (\"setara dengan menumpuk 1.600 gajah\", \"seluas 32.000 kolam renang olimpiade\", \"setinggi "
            "tiga Menara Eiffel\", \"seberat 50 mobil\", \"cara kerjanya seperti lampu lava\"), tulis benda PEMBANDING "
            "itu dalam bahasa Inggris untuk dicari fotonya, 1-3 kata, misalnya \"African elephant\", \"Olympic swimming "
            "pool\", \"Eiffel Tower\", \"car\", \"lava lamp\". Isi \"\" kalau tidak ada perbandingan.\n"
            "- jumlah: angka pada perbandingan itu sebagai bilangan bulat (1600 untuk \"1.600 gajah\", 3 untuk \"tiga "
            "Menara Eiffel\"); 0 kalau perbandingannya tanpa angka atau tidak ada perbandingan.\n"
            "- latar: klip stock video dalam bahasa Inggris, 2-4 kata umum, untuk LATAR BERGERAK adegan itu: TEMPAT "
            "nyata tempat hal yang dibahas berada, yang pasti ada di situs stock video, misalnya \"deep sea "
            "underwater\" untuk palung laut atau lempeng di dasar samudra, \"volcano lava eruption\" untuk gunung "
            "berapi, \"galaxy stars space\" untuk galaksi atau bintang jauh, \"planet earth from space\" untuk poros, "
            "orbit, atau iklim Bumi, \"jungle river aerial\" untuk hewan hutan tropis. Pilih tempat yang paling dekat "
            "dengan yang dibahas, bukan yang sekadar satu kategori (galaksi bertabrakan bukan gambaran poros Bumi). "
            "Harus tetap di DUNIA TOPIK video ini: jangan gurun, gunung, kota, awan, atau laboratorium kalau yang "
            "dibahas bukan itu. Adegan pembanding (gajah, Everest) tetap memakai tempat topik utamanya.\n"
            "Kalimat ajakan (tonton, link di bawah, subscribe, tulis di kolom komentar): JANGAN ikon, tombol, logo, "
            "atau layar — tulis visual paling kuat tentang topik video, sama seperti adegan sebelumnya.\n"
            f"Jawab dengan nomor adegan yang sama.\n\nADEGAN:\n{daftar}")}]
        # Jumlah item dikunci lewat schema: tanpa ini gemma kadang menjawab {"adegan": []}.
        schema = json.loads(json.dumps(SCHEMA_CARI))
        schema["properties"]["adegan"].update(minItems=len(bagian), maxItems=len(bagian))
        if artikel:
            item = schema["properties"]["adegan"]["items"]
            item["properties"]["artikel"] = {"type": "integer"}
            item["required"].append("artikel")
        for coba in range(3):
            try:
                j = ollama.chat_json(cfg, pesan, schema, batal=batal, maks_token=170 * len(bagian) + 100,
                                     suhu=0.3 + coba * 0.3)
            except (RuntimeError, ValueError) as e:
                log(f"Kata kunci adegan {mulai + 1}-{mulai + len(bagian)} gagal ({e})")
                continue
            items = [x for x in j.get("adegan", []) if isinstance(x, dict)]
            nomor_cocok = sum(1 for x in items if mulai < _int(x.get("no")) <= mulai + len(bagian))
            for posisi, item in enumerate(items[:len(bagian)]):
                # Pakai nomor dari AI; kalau nomornya ngawur, pakai urutan.
                no = _int(item.get("no")) - 1 if nomor_cocok == len(items) else mulai + posisi
                if mulai <= no < mulai + len(bagian):
                    hasil[no] = {k: str(item.get(k) or "").strip()[:60] for k in ("a", "b", "c")}
                    hasil[no]["lihat"] = " ".join(str(item.get("lihat") or "").split())[:160]
                    hasil[no]["subjek"] = " ".join(str(item.get("subjek") or "").split())[:60]
                    hasil[no]["teks_layar"] = " ".join(str(item.get("teks_layar") or "").split()).upper()[:28]
                    hasil[no]["latar"] = " ".join(str(item.get("latar") or "").split())[:50]
                    analogi = " ".join(str(item.get("analogi") or "").split())[:40]
                    if analogi:
                        hasil[no]["analogi"], hasil[no]["jumlah"] = analogi, max(0, _int(item.get("jumlah")))
                    nomor = _int(item.get("artikel"))
                    if 1 <= nomor <= len(artikel):
                        hasil[no]["artikel"] = artikel[nomor - 1]
            if sum(1 for h in hasil[mulai:mulai + len(bagian)] if h and (h["a"] or h["b"])) >= len(bagian) * 0.8:
                break
        log(f"Kata kunci footage: {min(mulai + kelompok, len(adegan))}/{len(adegan)} adegan")
    # Adegan yang tetap gagal meminjam kata kunci adegan terdekat yang berhasil (masih satu bahasan), bukan kata kunci
    # cadangan acak: dulu adegan lempeng tektonik mendapat "desert dunes aerial" dan menampilkan unta di gurun.
    berhasil = [i for i, h in enumerate(hasil) if h and (h["a"] or h["b"])]
    for i, h in enumerate(hasil):
        if h and (h["a"] or h["b"]):
            if not h["b"]:
                h["b"] = h.get("latar") or cadangan(fakta)[i % 10]
        elif berhasil:
            dekat = min(berhasil, key=lambda j: (abs(j - i), j > i))  # seri: dahulukan adegan sebelumnya
            hasil[i] = {**{k: v for k, v in hasil[dekat].items() if k not in ("analogi", "jumlah")},
                        "teks_layar": "", "pinjam_q": True}
        else:
            hasil[i] = {"a": "", "b": cadangan(fakta)[i % 10], "c": "", "pinjam_q": True}
    # Ajakan "Tonton sekarang lewat link di bawah" pernah dicarikan "video link icon" → ikon Iconfinder di akhir
    # Reels. Adegan ajakan yang kata kuncinya ikon/tombol/layar memakai kata kunci adegan sebelumnya (topiknya).
    for i in range(1, len(hasil)):
        h = hasil[i]
        if _AJAKAN.search(adegan[i]) and _IKON.search(" ".join(h.get(k) or "" for k in ("a", "b", "c", "lihat", "subjek"))):
            hasil[i] = dict(hasil[i - 1], teks_layar="")  # angka adegan sebelumnya tidak ikut tampil di ajakan
    return hasil


_AJAKAN = re.compile(r"\b(link|tautan|subscribe|langganan|komentar|follow|ikuti|like|bagikan|share|tonton)\b", re.I)
_IKON = re.compile(r"\b(icons?|ikon|buttons?|tombol|screens?|layar|links?|tautan|subscribe|logo|youtube|comments?|"
                   r"komentar|notification|notifikasi|bell|lonceng)\b", re.I)
