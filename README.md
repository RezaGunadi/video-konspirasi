# 🕵️ Video Konspirasi AI

Teks → naskah (AI lokal Ollama, untuk UFO, makhluk legendaris, bumi datar, benua di balik Antartika, dll.) → suara narator → footage dicari otomatis → video jadi (MP4 + subtitle + thumbnail + deskripsi).
Bawaannya: channel fakta (gaya **Sains & penemuan**, tampilan **Dokumenter cerah**, maskot **Si Kepo**, narasi
dengan **suaramu sendiri**), visual mayoritas klip video dengan foto sebagai stiker. Gaya misteri/konspirasi
("Meyakinkan", "Plot twist", dll.) tetap bisa dipilih.
Semua gratis. Yang butuh internet: suara (Microsoft Edge TTS), riset Wikipedia, dan pencarian footage.

## Cara pakai

1. Klik dua kali **`start.bat`**. Browser terbuka di http://localhost:3220
   (pastikan aplikasi Ollama jalan).
2. Pilih mode:
   - **🤖 AI tulis naskah**: isi topik/catatan, misal `Misteri Insiden Roswell 1947`.
   - **📜 Bacakan teks saya**: tempel naskah jadi, dibacakan apa adanya.
3. Pilih format (Shorts 9:16 / YouTube 16:9), panjang, dan suara (klik **🔊 Dengar contoh**).
4. Klik **🎬 Buat Video**. Proses berjalan di antrian, bisa ditinggal.
5. Klik proyeknya untuk melihat video, menyalin judul/deskripsi/hashtag, mengedit naskah,
   atau **ganti footage** per shot (🔄 berikutnya, 🖼️ pilih dari kandidat, 📁 pakai file sendiri),
   lalu **Render ulang**.

Hasil ada di folder `output\` (video, thumbnail.jpg, naskah.txt, deskripsi.txt berisi kredit footage).

## Format & durasi

- **Portrait 9:16** (Shorts/Reels/TikTok), **Landscape 16:9** (YouTube), atau **Panjang + Reels**: satu topik
  jadi video YouTube + 1–5 reels portrait. Tiap reels punya naskah teaser sendiri dengan fokus berbeda (tidak
  membongkar jawabannya) dan diakhiri ajakan menonton video lengkapnya. Setelah video panjang diupload, tempel
  link-nya di halaman proyek: deskripsi semua reels langsung diperbarui.
- Durasi **30 detik sampai 20 menit**. Video di atas 3 menit ditulis per bagian (AI menyusun kerangka dulu,
  lalu menulis tiap bagian) supaya tidak mengulang-ulang, dan deskripsinya dapat **daftar isi / chapter
  YouTube** otomatis (00:00 Pembuka, 01:25 …).
- Form menampilkan perkiraan lama proses. Patokan di laptop ini: Shorts 1 menit ±15–20 menit,
  video 10 menit ±1,5 jam (separuhnya untuk AI memilih footage — matikan kalau mau cepat).
- YouTube Shorts maksimal 3 menit; video vertikal yang lebih panjang tetap bisa untuk TikTok/Reels.

## ♻️ Re-create: beberapa short dari 1 video panjang

Pilih tab **♻️ Re-create video panjang**, lalu:

1. **Sumber**: video panjang yang sudah dibuat di aplikasi ini, atau upload video panjang milik sendiri
   (mp4/mov/mkv).
2. **Tema**: satu tema per baris = satu short. Kosongkan kalau mau AI yang memilih temanya dari isi video.
3. **Gaya**: *Teaser* (bikin penasaran, jawabannya di video panjang) atau *Mandiri* (cerita singkat yang tuntas).

Naskah tiap short **ditulis ulang** dari isi video sumber (bukan dipotong), lalu **dibacakan ulang**. Visualnya
diambil dari bagian sumber yang membahas hal yang sama:

- Sumber dari aplikasi ini: foto/klip aslinya dirender ulang ke 9:16 (tanpa subtitle lama), dan suaranya **sama
  persis** dengan video panjangnya (suara, kecepatan, nada).
- File upload: video ditranskrip dengan Whisper, potongan videonya dipakai sebagai footage. Suara baru disamakan
  jenis (pria/wanita), tinggi nada, dan kecepatan bicaranya. Kalau kamu centang "video & suara ini milik saya /
  sudah ada izin", warna suaranya juga disamakan dengan pembicara di video itu memakai **OpenVoice V2** (MIT, jalan
  lokal di CPU, model di `D:\tools\openvoice`). Opsi "samarkan subtitle di bagian bawah" menutup teks yang tertanam
  di video sumber.

Jangan dipakai untuk meniru suara atau mengunggah ulang video orang lain tanpa izin.

## Ide topik

Tombol **💡 Ide topik konspirasi** membuka 84 ide di 12 kategori (UFO, luar angkasa, makhluk legendaris,
bumi datar & benua rahasia, peradaban kuno, proyek rahasia, konspirasi yang ternyata nyata, tokoh,
laut & langit, kutukan, teknologi, Misteri Nusantara). Klik satu ide untuk dipakai, atau centang beberapa
lalu **Antrikan** sekaligus. **🤖 Minta AI 8 ide baru** membuat ide tambahan; tiap ide dicek ke Wikipedia
dan yang topiknya tidak ditemukan dibuang (model kecil kadang mengarang nama tempat/makhluk).
Topik tragedi nyata yang baru, kesehatan/vaksin, pemilu, dan teori yang menyerang kelompok tidak dimasukkan.

## Otomatis dari file .txt

Taruh file `.txt` di folder `input\`. Tiap file otomatis jadi 1 video memakai pengaturan terakhir di form,
lalu filenya dipindah ke `input\sudah-diproses\`. Bisa juga upload banyak .txt sekaligus lewat tombol
**📂 Ambil dari file .txt** (centang *Tiap baris = 1 video* kalau satu file berisi daftar topik).

## Footage (tanpa login)

Semua sumber ini bisa dipakai tanpa daftar/login/token:

| Sumber | Isi | Cocok untuk |
|---|---|---|
| Wikimedia Commons | foto & video, peta lama | tempat, tokoh, peristiwa nyata |
| NASA | foto & video luar angkasa | bulan, UFO, satelit, bumi dari luar angkasa |
| Mixkit | stock video HD (hanya item berlisensi *Free*; item *Restricted* dibuang otomatis) | latar suasana: kabut, kota malam, gurun, laut |
| Archive.org | film arsip public domain | era Perang Dingin, ekspedisi Antartika 1947 |
| Openverse | foto bebas dari Flickr & museum | Loch Ness, hutan, danau, suasana |
| The Met & Cleveland Museum | lukisan, ukiran, peta kuno (CC0) | makhluk legendaris, naga, peta bumi datar kuno |

**Gambar topik (paling on point):** sebelum mencari per adegan, aplikasi mengambil semua gambar dari artikel
Wikipedia topiknya + kategori Wikimedia Commons-nya (misalnya kategori "Loch Ness Monster": foto Surgeon 1934,
sketsa saksi, model plesiosaurus) dan ilustrasi/lukisan subjeknya. Gambar-gambar ini selalu ikut dinilai AI di
setiap adegan. AI terus melihat kandidat (maks. 3 ronde) sampai gambar bagusnya cukup; kalau tetap kurang,
jumlah shot dikurangi daripada memakai gambar jelek. Gambar amatir, kartun, mural, kerajinan, dan papan nama
diberi skor rendah.

Video lama bisa diperbarui dengan tombol **🔎 Cari ulang semua footage** di halaman proyek (naskah & suara tetap).

Per adegan, AI membuat 3 kata kunci: **hal spesifik** (misal "Ross Ice Shelf"), **visual umum**
(misal "foggy lake"), dan **ilustrasi/arsip lama** (misal "sea serpent engraving", "medieval world map").
Lalu AI (gemma, bisa melihat gambar) menilai kandidat dalam kolase 2x2 dan memilih yang paling nyambung;
kalau 4 kandidat pertama kurang cocok, AI melihat 4 kandidat berikutnya.

- Openverse dibatasi ±200 pencarian/hari per koneksi internet; hasil pencarian disimpan 7 hari supaya hemat.
- Opsional: API key gratis **Pexels**/**Pixabay** di ⚙️ Setelan untuk tambahan stock video HD modern — dicari
  untuk hal spesifiknya juga (misal "chicken", "ostrich"), jadi topik hewan/alam dapat banyak klip video asli.

**Gerak visual "Hidup"** (bawaan, di Pengaturan lanjutan): klip video asli didahulukan dari foto yang sama tepatnya,
dan foto dibuat bergerak **2.5D (parallax)**: model kedalaman Depth Anything V2 (jalan di CPU, ±1 detik per foto)
memisahkan benda depan dari latar, lalu kamera bergerak sehingga benda depan bergeser lebih jauh dari latarnya —
seperti klip pendek, bukan sekadar zoom. Pilih **Zoom/pan biasa** kalau ingin render lebih cepat.
- Kredit sumber otomatis ditulis di `deskripsi.txt`. Tempel ke deskripsi YouTube
  (wajib untuk foto berlisensi CC BY / CC BY-SA). Lisensi item Archive.org ditentukan pengunggahnya;
  kalau ragu, ganti shot itu lewat tombol 🔄 Ganti.

## Disclaimer

Di form (bagian **Disclaimer**) atau per proyek:
- **Teks di awal**: kotak teks kecil di bagian atas selama 5 detik pertama.
- **Kartu di akhir**: layar gelap bertuliskan DISCLAIMER + teks, dibacakan narator.
- **Keduanya** / **Tanpa disclaimer**.

Teksnya bisa diedit, dan selalu ikut masuk ke `deskripsi.txt` (kecuali dipilih tanpa disclaimer).

## 🔭 Channel fakta: gaya "Sains & penemuan" + tampilan "Dokumenter cerah" (bawaan)

Untuk channel berita sains/penemuan (seperti SISITERANG): isinya fakta, bukan teori atau opini.
- **Naskah**: dibuka dengan fakta paling mengejutkan → kenapa itu aneh (biasanya begini, kenyataannya begitu) →
  pertanyaan dijawab satu per satu oleh para ilmuwan, dengan analogi sehari-hari ("seperti lampu lava raksasa")
  dan pembanding skala → alasan bernomor "Pertama… Kedua… Ketiga…" lalu dirangkum → dampak yang bikin "wow".
  Dugaan ilmiah ditandai ("para ilmuwan menduga"). Inti ceritanya (pertanyaan → jawaban ilmuwan → fakta + artinya)
  disusun dulu supaya tidak menggantung.
- **Visual**: warna terang & tajam, transisi halus (tanpa glitch/kabut), kata kunci footage dokumenter (drone,
  satelit, diagram, peta, citra NASA), judul hook kuning, dan **angka/istilah kunci tampil besar** di tengah layar
  ("30 JUTA TAHUN", "MELEBAR 5 CM"; pindah ke atas kalau shot itu menampilkan stiker). Tanpa perbandingan
  "MIRIP?". Musik bawaan: musik dokumenter tenang buatan aplikasi (bebas hak cipta).
- Pilih gaya cerita lain (Meyakinkan, Plot twist, …) dan tampilan otomatis kembali ke Misterius.

## 🐣 Maskot "Si Kepo"

Maskot channel buatan aplikasi ini sendiri: makhluk bulat toska yang penasaran, bertopi penjelajah dengan kaca
pembesar. File di folder `maskot\`: `melambai`, `kaget`, `mikir`, `nunjuk`, `senang` (PNG transparan + SVG
sumbernya) dan `logo.png` (bisa dipakai untuk foto profil channel). Di video (centang **Maskot** di Pengaturan
lanjutan) ia muncul "memantul" di pojok kiri bawah ±2,5 detik dengan bunyi *pop*: kaget di pembuka, menunjuk saat
"Pertama/Kedua…", berpikir saat ada pertanyaan, kaget saat fakta mengejutkan, senang saat rangkuman, melambai di
ajakan akhir (paling sering sekali tiap ±9 detik, tidak bersamaan dengan stiker). Logo kecil tampil di pojok kanan
atas sepanjang video. Mau maskot sendiri? Ganti PNG di folder `maskot\` dengan nama yang sama.

## Gaya cerita "Meyakinkan"

Narator bicara seperti host YouTube yang ngobrol ke kamera ("aku" ke "kamu"), bukan narator dokumenter:
- dibuka dengan hal yang pasti pernah didengar penonton, lalu dibelokkan ("tapi yang mau aku tunjukin bukan teori,
  ini yang tercatat"), lalu menjawab skeptis penonton ("mungkin kamu mikir, ah teori konspirasi lagi…");
- rekam jejak fakta nyata dari riset Wikipedia (tahun, nama, tempat, angka) disusun berurutan, lalu dua fakta
  ditaruh berdampingan dan ditutup pertanyaan retoris: "Kebetulan?", "Coba pikir.";
- menjelang akhir: versi resmi singkat secara adil + sikap "ini kacamata aku, bisa jadi aku salah", lalu pertanyaan
  ke penonton.

Yang membuatnya meyakinkan adalah fakta nyata yang spesifik; kesimpulan konspirasinya selalu berupa pertanyaan atau
kecurigaan, bukan klaim karangan (kutipan dan angka tetap hanya dari bahan riset). Gaya lama (Plot twist, Bangun
teori, Seimbang, Edukasi) masih bisa dipilih.

**Supaya penonton langsung nangkep** (gaya Meyakinkan, Plot twist, Bangun teori): sebelum menulis, AI menyusun
*inti cerita* dulu — pertanyaan besar → teorinya dalam satu kalimat → 3 fakta nyata masing-masing dengan "artinya…"
→ versi resmi → kesimpulan yang menjawab pertanyaan. Naskah lalu wajib menyebut teorinya di 3 kalimat pertama,
menjelaskan arti tiap fakta, dan menjawab pertanyaan pembuka di akhir (tidak menggantung). Video ≤75 detik memakai
2 bukti terkuat saja. Inti ceritanya tampil di log proyek.

## 🎙️ Suara saya (klon)

Pilih **🎙️ Suara saya** di daftar suara: naskah dibacakan Edge TTS (Ardi, nadanya digeser ke nada bicaramu), lalu
warna suaranya diubah jadi suaramu dengan **OpenVoice V2** (lokal, CPU, ±45 detik untuk narasi 1 menit). Intonasi
dan tempo tetap dari TTS, warna suaranya dari kamu. Profilnya di `data\suara-saya\`: 24 potongan bicara paling
bersih (167 detik) dari 3 video channel YouTube milik sendiri, dipilih dan dikonfirmasi pemilik suaranya. Rekaman
suara ini **tidak** ikut ke repo Git (folder `data\` diabaikan) supaya suaramu tidak bisa dikloning orang lain;
salin `data\suara-saya\` ke komputer lain lewat LAN/flashdisk.
Uji naskah Area 51: kemiripan warna suara (sidik OpenVoice) naik dari 0,60 (Ardi) ke 0,84 (batas atas rekaman asli
0,87); Whisper masih mengenali 92% kata (Ardi 97%). Slider *nada* tidak dipakai untuk suara ini. Hanya untuk suara
milik sendiri.

## Tata visual "Video + stiker" (bawaan)

Meniru gaya video konspirasi/berita YouTube yang potongannya cepat:
- **Mayoritas klip video**, dipotong ±3,5 detik (Shorts) / ±4 detik (YouTube). Di mode ini AI juga menilai tiap klip
  sebagai **latar** (hutan berkabut untuk kisah Bigfoot, ruang arsip untuk dokumen rahasia), jadi klip suasana yang
  pas tetap dipakai walaupun subjeknya tidak tampak. Satu klip panjang (film arsip) bisa dipakai beberapa shot dengan
  potongan berbeda.
- **Foto yang tepat jadi stiker** di atas klip: bingkai putih, bayangan, sedikit miring, label kuning berisi subjek
  adegan, muncul "meletup" dengan bunyi *plop*, lalu mengambang pelan. Di Shorts letaknya di tengah atas (tidak
  menutupi subtitle); di YouTube bergantian kiri/kanan. Stiker menunggu judul hook di 3 detik pertama hilang.
- **Analogi divisualkan**: narasi "setara dengan menumpuk 1.600 gajah" → AI menandai benda pembandingnya & jumlahnya,
  bendanya dipotong dari latar (model ISNet, ±180 MB, diunduh otomatis ke `tools/rembg` saat pertama dipakai, jalan di
  CPU ±2 detik per foto) lalu ditumpuk jadi gunungan berlabel "×1.600". Foto yang bendanya tidak utuh (close-up
  wajah, terpotong tepi foto, kecil di tengah pemandangan) ditolak otomatis; benda yang tidak bisa dipotong (gunung,
  lapangan) ditumpuk sebagai foto berbingkai.
- **Foto layar penuh maksimal 3 detik**, hanya kalau klipnya habis atau sesekali untuk foto yang sangat kuat (total
  foto layar penuh dijaga di bawah ±25%).
- Di halaman proyek tiap shot menampilkan stikernya; tombol **✖ Stiker** membuang stiker (lalu Render ulang).

Tanpa API key, klip video hanya dari Wikimedia, NASA, Archive.org, dan Mixkit. Mixkit memblokir sementara (±30 menit)
kalau dipanggil terlalu sering, dan topik tertentu (misalnya situs di Indonesia) jarang punya klip. **Isi API key
gratis Pexels dan Pixabay di ⚙️ Setelan** supaya hampir semua adegan dapat klip video; tanpa itu sebagian adegan
tetap jatuh ke foto ≤3 detik. Pilih **Klasik** di Pengaturan lanjutan untuk tata visual lama (foto & video layar
penuh 4–7 detik). Proyek yang dibuat sebelum fitur ini tetap memakai Klasik.

## Gaya misterius

Pilihan **Gaya visual: Misterius** (bawaan) memberi:
- grading gelap & dingin (sorotan diredam, bayangan kebiruan), vignette, grain film, kedip cahaya halus;
- kabut tipis yang bergerak pelan di atas gambar;
- glitch singkat (pecahan warna RGB + noise) di setiap pergantian adegan, ditemani suara *whoosh*;
- judul hook besar di 3 detik pertama (diambil dari teks thumbnail) + dentuman berat di awal;
- kata yang sedang diucapkan di subtitle berwarna kuning dan "meletup".
Gambar yang sama-sama cocok didahulukan yang bernuansa gelap/kelam/arsip hitam-putih.

## Sinkron suara & subtitle

Naskah dibacakan sekali jalan (intonasi alami). Waktu tiap kata subtitle lalu dicocokkan dengan suara
oleh **Whisper** (pengenal suara, jalan di laptop; model di `D:	ools\hf-cache`), karena waktu dari
Edge TTS meleset 0,4–1 detik di sekitar angka ("9.000 hingga 20.000"). Teks subtitle tetap sesuai naskah.

## Suara lebih alami

Centang **Suara lebih alami** (bawaan): jeda antarkalimat diatur seperti narator manusia — paragraf baru lebih
lama, pertanyaan dibiarkan "mendarat", jeda dramatis sebelum "Tapi…/Ternyata…" — (Ardi aslinya menjeda seragam
±1,1 detik di tiap titik), lalu diberi warna rekaman (EQ hangat, kompresi halus, sedikit ruang). Naskah juga ditulis
untuk diucapkan: panjang kalimat bervariasi, kata lisan secukupnya, tanpa kata baku yang kaku.

Pilihan suara tambahan: **Andrew, Brian, Ava, Emma (multibahasa)** — intonasinya lebih ekspresif seperti orang
ngobrol dan bisa membaca bahasa Indonesia (kadang dengan sedikit logat). Bandingkan lewat 🔊 Dengar contoh, atau
dengar file di `data\contoh-suara\` (versi `-1-asli` vs `-2-alami`).

## Musik latar

Taruh `.mp3` bebas royalti (misal YouTube Audio Library) di folder `musik\`. Dipilih acak, volumenya
otomatis turun saat narator bicara. Kalau folder kosong, dipakai musik ambient mencekam buatan aplikasi
sendiri (bebas hak cipta).

## Catatan konten

Naskah dibuat dengan aturan: fakta dibedakan dari klaim teori, angka/nama/kutipan hanya dari bahan riset,
dan ada penjelasan resmi di akhir. Tetap baca naskahnya sebelum upload. Konten konspirasi yang disajikan
sebagai fakta bisa kena aturan misinformasi YouTube/TikTok (video dibatasi atau tidak dimonetisasi).

## Mini PC sebagai "otak AI" (opsional)

Laptop ini hanya punya ±2 GB RAM bebas saat model AI (8,6 GB) dimuat, sehingga AI menulis 1,6–2 token/detik.
Ollama bisa dijalankan di mini PC (RAM 16 GB) dan dipakai aplikasi lewat LAN; render tetap di laptop (GPU NVENC).
Di mini PC (Windows) jalankan sekali `minipc\siapkan-minipc.bat` → *Run as administrator*: memasang OpenSSH
Server (masuk hanya dengan kunci dari laptop ini, `~/.ssh/minipc_ed25519`), membuka port 22 & 11434 hanya untuk
jaringan lokal, mengizinkan Ollama diakses dari LAN, lalu menampilkan CPU/RAM/IP-nya. Setelah itu Ollama & model
bisa dipasang dari laptop, dan `ollama_url` di setelan diarahkan ke `http://<IP mini PC>:11434`. Ollama di LAN
tidak memakai password: siapa pun di jaringan yang sama bisa memakainya.

## Teknis

- Python venv: `.venv` · server: `app.py` (port 3220, hanya bisa dibuka dari laptop ini)
- ffmpeg: `D:\tools\ffmpeg\bin` (render pakai GPU NVENC kalau ada)
- Model: setelan **Model AI**, bawaan `sosmed-ai` (sama dengan Sosmed AI supaya tidak dimuat dua kali)
- Data proyek & cache: `data\`
