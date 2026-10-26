const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, init);
  const j = r.headers.get('content-type')?.includes('json') ? await r.json() : {};
  if (!r.ok || j.ok === false) throw new Error(j.galat || `HTTP ${r.status}`);
  return j;
}

const STATUS = { antri: 'Antri', jalan: 'Diproses', cek_naskah: 'Cek naskah', selesai: 'Selesai', gagal: 'Gagal', dibatalkan: 'Dibatalkan' };
const LANGKAH = { riset: 'Riset', naskah: 'Naskah', adegan: 'Adegan', suara: 'Suara', footage: 'Footage', render: 'Render' };
const BANTU_MODE = {
  tulis: 'Tulis topik atau catatan (boleh singkat, misal "Teori Area 51"). AI riset fakta, menulis naskah, lalu jadi video.',
  bacakan: 'Tempel naskah yang sudah jadi. Teks dibacakan apa adanya, AI hanya mencari footage yang pas.',
  recreate: 'Buat beberapa short portrait dari SATU video panjang: naskah ditulis ulang per tema, suara dibacakan ulang dan disamakan dengan video sumbernya.',
};
const PLACEHOLDER = {
  tulis: 'Contoh:\nMisteri Insiden Roswell 1947 — benarkah yang jatuh itu UFO?\n\nAtau catatan bebas: poin-poin yang mau dibahas, sudut pandang, dsb.',
  bacakan: 'Tempel naskah lengkap di sini…',
  recreate: '',
};

const form = { mode: 'tulis', format: '9:16' };
let fileTerpilih = [];
let statusTerakhir = null;

// ---------------------------------------------------------------- status & setelan
async function muatStatus() {
  const s = await api('/api/status');
  statusTerakhir = s;
  const c = s.config;
  $('#chip').innerHTML = [
    [s.ollama, s.ollama ? `Ollama ✓ (${c.model})` : 'Ollama mati'],
    [s.ffmpeg, s.encoder === 'h264_nvenc' ? 'Render GPU ✓' : 'Render CPU'],
    [true, 'Footage tanpa login: 9 sumber (termasuk video Mixkit)'],
    [c.sumber_web === 'semua' ? 'netral' : true, c.sumber_web === 'semua' ? 'Gambar web: semua (cek hak cipta)' : c.sumber_web === 'berlisensi' ? 'Gambar web: berlisensi' : 'Gambar web: mati'],
    [c.pexels_key_ada || 'netral', c.pexels_key_ada ? 'Pexels ✓' : 'Pexels: disarankan (lebih banyak video)'],
    [c.pixabay_key_ada || 'netral', c.pixabay_key_ada ? 'Pixabay ✓' : 'Pixabay: disarankan (lebih banyak video)'],
    [s.musik > 0 || 'netral', s.musik > 0 ? `${s.musik} musik` : 'Musik: dengung bawaan'],
  ].map(([ok, t]) => `<span class="chip ${ok === 'netral' ? 'netral' : ok ? 'ok' : 'no'}">${esc(t)}</span>`).join('');
  return s;
}

function isiForm(d, suara) {
  $('#suara').innerHTML = Object.entries(suara).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  pilihSeg('#segMode', d.mode); form.mode = d.mode;
  pilihSeg('#segFormat', d.format); form.format = d.format;
  $('#durasi').value = String(d.durasi);
  if (!$('#durasi').value) $('#durasi').value = '60';
  for (const k of ['suara', 'kecepatan', 'nada', 'volume_musik', 'gaya', 'isi_layar', 'disclaimer', 'teks_disclaimer', 'gaya_naskah', 'cta', 'cta_reels', 'animasi', 'visual']) $('#' + k).value = d[k] ?? '';
  if (!$('#animasi').value) $('#animasi').value = 'hidup';
  if (!$('#visual').value) $('#visual').value = 'video_stiker';
  if (!$('#gaya_naskah').value) $('#gaya_naskah').value = 'meyakinkan';
  $('#jumlah_reels').value = String(d.jumlah_reels ?? 3);
  $('#durasi_reels').value = String(d.durasi_reels ?? 45);
  if (!$('#durasi_reels').value) $('#durasi_reels').value = '45';
  for (const k of ['riset', 'cek_gambar', 'cek_naskah', 'subtitle', 'musik', 'maskot']) $('#' + k).checked = !!d[k];
  $('#suara_alami').checked = d.suara_alami ?? true;
  segarkanLabel();
  ubahMode();
}

function pilihSeg(sel, v) { $$(sel + ' button').forEach((b) => b.classList.toggle('aktif', b.dataset.v === v)); }
function segarkanLabel() {
  $('#vKecepatan').textContent = `(${(+$('#kecepatan').value > 0 ? '+' : '') + $('#kecepatan').value}%)`;
  $('#vNada').textContent = `(${(+$('#nada').value > 0 ? '+' : '') + $('#nada').value})`;
  $('#vVolume').textContent = `(${$('#volume_musik').value}%)`;
}
function ubahMode() {
  $('#bantuMode').textContent = BANTU_MODE[form.mode];
  $('#teks').placeholder = PLACEHOLDER[form.mode];
  const rc = form.mode === 'recreate';
  $('#kolomDurasi').style.display = form.mode === 'tulis' ? '' : 'none';
  $('#kolomGayaNaskah').style.display = form.mode === 'tulis' ? '' : 'none';
  $('#kolomTopik').hidden = rc;
  $('#kolomFormat').hidden = rc;
  $('#kolomRecreate').hidden = !rc;
  if (rc) { $('#kolomReels').hidden = true; muatSumberRecreate(); }
  $('#riset').closest('label').style.display = form.mode === 'tulis' ? '' : 'none';
  $('#cek_naskah').closest('label').style.display = form.mode === 'tulis' ? '' : 'none';
  perbaruiInfo();
}

// Perkiraan lama proses di laptop ini (gemma 12B ±2 token/detik), dari pengukuran video uji.
function perkiraanDetik(kata, format, tulis, cekGambar) {
  const narasi = kata / 2.2;
  const adegan = Math.max(1, Math.round(kata / (format === '9:16' ? 13 : 26)));
  const shot = Math.ceil(narasi / (format === '9:16' ? 5 : 7));
  const bagian = narasi > 180 ? Math.max(4, Math.min(14, Math.round(narasi / 80))) : 0;
  const naskah = tulis ? kata * 0.8 + (bagian ? bagian * 40 + 60 : 30) : 0;
  return 30 + naskah + 60 + adegan * 12 + adegan * 1.5 + adegan * (cekGambar ? 65 : 12) + shot * 2.5 + narasi * 0.3;
}

function teksMenit(detik) {
  const m = Math.round(detik / 60);
  return m < 60 ? `±${Math.max(1, m)} menit` : `±${Math.floor(m / 60)} jam ${m % 60} menit`;
}

// ---------------------------------------------------------------- re-create
let fileSumber = null;
async function muatSumberRecreate() {
  const sel = $('#rcSumber');
  const lama = sel.value;
  const { proyek } = await api('/api/proyek');
  const panjang = proyek.filter((p) => p.status === 'selesai' && p.opsi.format === '16:9' && p.hasil?.video);
  sel.innerHTML = panjang.map((p) => `<option value="proyek:${p.id}">🎬 ${esc(p.judul || p.nama)} (${Math.round((p.hasil.durasi || 0) / 60 * 10) / 10} menit)</option>`).join('')
    + '<option value="file">📁 Upload video panjang milik sendiri…</option>';
  if ([...sel.options].some((o) => o.value === lama)) sel.value = lama;
  if (!$('#rcCta').value) $('#rcCta').value = $('#cta_reels').value || 'Jawabannya ada di video lengkapnya. Tonton sekarang lewat link di bawah.';
  ubahSumberRecreate();
}
function ubahSumberRecreate() {
  const file = $('#rcSumber').value === 'file';
  $('#rcBarisFile').hidden = !file;
  $('#rcBarisIzin').hidden = !file || !$('#rcSamakan').checked;
  $('#rcInfoSuara').textContent = statusTerakhir?.suara_mirip
    ? 'Kalau dicentang, warna suara narasi baru disamakan dengan pembicara di video ini (OpenVoice, jalan di laptop). Tanpa izin, hanya jenis suara, nada, dan kecepatannya yang disamakan.'
    : 'OpenVoice belum terpasang: hanya jenis suara, nada, dan kecepatannya yang disamakan.';
}
$('#rcSumber').addEventListener('change', ubahSumberRecreate);
$('#rcSamakan').addEventListener('change', ubahSumberRecreate);
$('#rcFile').addEventListener('change', (e) => { fileSumber = e.target.files[0] || null; $('#rcNamaFile').textContent = fileSumber ? `${fileSumber.name} (${Math.round(fileSumber.size / 1048576)} MB)` : 'Belum ada file'; });

async function buatRecreate() {
  let sumber;
  if ($('#rcSumber').value === 'file') {
    if (!fileSumber) throw new Error('Pilih file video sumbernya dulu.');
    $('#infoBuat').textContent = 'Mengupload video sumber…';
    const fd = new FormData();
    fd.append('file', fileSumber);
    const up = await api('/api/recreate/upload', { body: fd });
    sumber = { jenis: 'file', path: up.path, nama: up.nama };
  } else {
    sumber = { jenis: 'proyek', id: $('#rcSumber').value.replace(/^proyek:/, '') };
  }
  const tema = $('#rcTema').value.split('\n').map((t) => t.replace(/^\s*(?:[-•*]|\d+[.)])\s*/, '').trim()).filter(Boolean);
  return api('/api/recreate', { body: {
    sumber, tema, jumlah: +$('#rcJumlah').value, opsi: opsiForm(),
    rc: { durasi: +$('#rcDurasi').value, gaya_short: $('#rcGaya').value, cta: $('#rcCta').value.trim(),
          samakan_suara: $('#rcSamakan').checked, izin: $('#rcIzin').checked, tutup_bawah: $('#rcTutup').checked },
  } });
}

function perbaruiInfo() {
  const tulis = form.mode === 'tulis';
  const durasi = +$('#durasi').value;
  const kata = tulis ? durasi * 2.2 : ($('#teks').value.trim().split(/\s+/).filter(Boolean).length || 0);
  const detikVideo = kata / 2.2;
  const cek = $('#cek_gambar').checked;
  const info = [];
  $('#kolomReels').hidden = form.format !== 'keduanya';
  const nReels = +$('#jumlah_reels').value || 1;
  const dReels = +$('#durasi_reels').value || 45;
  if (form.format === 'keduanya') {
    info.push(`Jadi ${nReels + 1} video: 1 video panjang landscape 16:9${tulis ? ' ' + teksMenit(detikVideo) : ''} + ${nReels} reels portrait 9:16 ±${dReels} detik (naskah teaser beda-beda).`);
  } else if (form.format === '9:16' && detikVideo > 180) {
    info.push('<span class="peringatan">⚠️ YouTube Shorts maksimal 3 menit. Lebih dari itu tetap bisa untuk TikTok/Reels, atau pilih "Keduanya".</span>');
  }
  if (kata) {
    let t = perkiraanDetik(kata, form.format === 'keduanya' ? '16:9' : form.format, tulis, cek);
    if (form.format === 'keduanya') t += nReels * perkiraanDetik(dReels * 2.2, '9:16', true, cek);
    info.push(`Perkiraan proses: ${teksMenit(t)}${cek && t > 1800 ? ' (matikan "AI melihat & memilih footage" di Pengaturan lanjutan supaya lebih cepat)' : ''}.`);
  }
  $('#infoDurasi').innerHTML = info.join('<br>');
}

function opsiForm() {
  return {
    mode: form.mode, format: form.format, durasi: +$('#durasi').value, suara: $('#suara').value,
    kecepatan: +$('#kecepatan').value, nada: +$('#nada').value, volume_musik: +$('#volume_musik').value,
    gaya: $('#gaya').value, isi_layar: $('#isi_layar').value,
    disclaimer: $('#disclaimer').value, teks_disclaimer: $('#teks_disclaimer').value.trim(),
    gaya_naskah: $('#gaya_naskah').value, cta: $('#cta').value.trim(),
    jumlah_reels: +$('#jumlah_reels').value, durasi_reels: +$('#durasi_reels').value, cta_reels: $('#cta_reels').value.trim(),
    riset: $('#riset').checked, cek_gambar: $('#cek_gambar').checked, cek_naskah: $('#cek_naskah').checked,
    subtitle: $('#subtitle').checked, musik: $('#musik').checked, maskot: $('#maskot').checked,
    suara_alami: $('#suara_alami').checked, animasi: $('#animasi').value, visual: $('#visual').value,
  };
}

// Gaya cerita fakta ↔ tampilan cerah; gaya misteri/konspirasi ↔ tampilan misterius (masih bisa diubah manual).
$('#gaya_naskah').addEventListener('change', () => {
  const fakta = ['sains', 'edukasi'].includes($('#gaya_naskah').value);
  if (fakta && $('#gaya').value === 'misterius') $('#gaya').value = 'cerah';
  if (!fakta && $('#gaya').value === 'cerah') $('#gaya').value = 'misterius';
});
$('#btnDisclaimerBawaan').addEventListener('click', () => { $('#teks_disclaimer').value = statusTerakhir?.disclaimer_bawaan || ''; });
$('#segMode').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; form.mode = b.dataset.v; pilihSeg('#segMode', form.mode); ubahMode(); });
$('#segFormat').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; form.format = b.dataset.v; pilihSeg('#segFormat', form.format); perbaruiInfo(); });
['durasi', 'cek_gambar', 'jumlah_reels', 'durasi_reels'].forEach((k) => $('#' + k).addEventListener('change', perbaruiInfo));
$('#teks').addEventListener('input', () => { if (form.mode === 'bacakan') perbaruiInfo(); });
['kecepatan', 'nada', 'volume_musik'].forEach((k) => $('#' + k).addEventListener('input', segarkanLabel));

$('#fileTxt').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  if (!files.length) return;
  if (files.length === 1) {
    fileTerpilih = [];
    $('#teks').value = await files[0].text();
    $('#infoBuat').textContent = `Isi ${files[0].name} dimuat ke kotak teks.`;
  } else {
    fileTerpilih = files;
    $('#infoBuat').textContent = `${files.length} file dipilih — tiap file jadi 1 video. (Kosongkan pilihan dengan memuat ulang halaman.)`;
  }
});

$('#btnContoh').addEventListener('click', async () => {
  const b = $('#btnContoh');
  b.disabled = true; b.textContent = '⏳ Membuat contoh…';
  try {
    const r = await fetch('/api/contoh-suara', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ suara: $('#suara').value, kecepatan: +$('#kecepatan').value, nada: +$('#nada').value, suara_alami: $('#suara_alami').checked }) });
    if (!r.ok) throw new Error((await r.json()).galat);
    const p = $('#pemutar');
    p.src = URL.createObjectURL(await r.blob());
    await p.play();
  } catch (err) { alert('Gagal: ' + err.message); }
  b.disabled = false; b.textContent = '🔊 Dengar contoh';
});

$('#btnBuat').addEventListener('click', async () => {
  const b = $('#btnBuat');
  const teks = $('#teks').value.trim();
  if (form.mode === 'recreate') {
    b.disabled = true;
    try {
      const r = await buatRecreate();
      $('#rcTema').value = '';
      $('#infoBuat').textContent = `✓ ${r.id.length} short masuk antrian.`;
      muatDaftar();
    } catch (err) { $('#infoBuat').textContent = 'Gagal: ' + err.message; }
    b.disabled = false;
    return;
  }
  if (!teks && !fileTerpilih.length) { $('#infoBuat').textContent = 'Isi teks atau pilih file .txt dulu.'; return; }
  b.disabled = true;
  try {
    let r;
    if (fileTerpilih.length) {
      const fd = new FormData();
      fileTerpilih.forEach((f) => fd.append('file', f));
      fd.append('opsi', JSON.stringify(opsiForm()));
      fd.append('per_baris', $('#perBaris').checked ? '1' : '0');
      r = await api('/api/proyek/upload', { body: fd });
      fileTerpilih = [];
    } else {
      r = await api('/api/proyek', { body: { teks, opsi: opsiForm(), per_baris: $('#perBaris').checked } });
    }
    $('#teks').value = '';
    $('#infoBuat').textContent = `✓ ${r.id.length} video masuk antrian.`;
    muatDaftar();
  } catch (err) { $('#infoBuat').textContent = 'Gagal: ' + err.message; }
  b.disabled = false;
});

// Setelan
$('#btnSetelan').addEventListener('click', async () => {
  const s = await muatStatus();
  $('#pexels_key').value = s.config.pexels_key;
  $('#pixabay_key').value = s.config.pixabay_key;
  $('#pantau_input').checked = !!s.config.pantau_input;
  $('#sumber_web').value = s.config.sumber_web || 'tidak';
  const models = s.models.length ? s.models : [s.config.model];
  $('#model').innerHTML = models.map((m) => `<option ${m.replace(/:latest$/, '') === s.config.model.replace(/:latest$/, '') ? 'selected' : ''}>${esc(m)}</option>`).join('');
  $('#modalSetelan').hidden = false;
});
$('#btnSimpanSetelan').addEventListener('click', async () => {
  await api('/api/config', { body: { pexels_key: $('#pexels_key').value, pixabay_key: $('#pixabay_key').value,
    model: $('#model').value, pantau_input: $('#pantau_input').checked, sumber_web: $('#sumber_web').value } });
  $('#modalSetelan').hidden = true;
  muatStatus();
});
$$('[data-buka]').forEach((b) => b.addEventListener('click', () => api('/api/buka/' + b.dataset.buka, { body: {} })));
$$('[data-tutup]').forEach((b) => b.addEventListener('click', () => { b.closest('.modal').hidden = true; if (b.closest('#modalDetail')) tutupDetail(); }));

// ---------------------------------------------------------------- daftar proyek
let daftarCache = [];
async function muatDaftar() {
  try {
    const { proyek } = await api('/api/proyek');
    daftarCache = proyek;
    $('#jumlahProyek').textContent = proyek.length ? `(${proyek.length})` : '';
    if (!proyek.length) { $('#daftarProyek').innerHTML = '<p class="bantu">Belum ada proyek.</p>'; return; }
    $('#daftarProyek').innerHTML = proyek.map((p) => {
      const gbr = p.status === 'selesai' && p.hasil?.thumbnail ? `style="background-image:url('/hasil/${p.id}/thumbnail?${encodeURIComponent(p.hasil.durasi)}')"` : '';
      const ikon = gbr ? '' : ({ selesai: '🎬', gagal: '⚠️', dibatalkan: '⏹️', cek_naskah: '📝', jalan: '⏳' }[p.status] || '🕒');
      const langkah = p.status === 'jalan' && p.langkah ? `${LANGKAH[p.langkah]} · ` : '';
      return `<div class="proyek" data-id="${p.id}">
        <div class="gbr" ${gbr}>${ikon}</div>
        <div><div class="nama">${esc(p.judul || p.nama)}</div>
          <div class="pesan">${esc(labelFormat(p.opsi))} · ${langkah}${esc(p.galat || p.pesan || '')}</div>
          ${['jalan', 'antri'].includes(p.status) ? `<div class="bar"><i style="width:${p.progres}%"></i></div>` : ''}</div>
        <span class="lencana ${p.status}">${STATUS[p.status] || p.status}${p.status === 'jalan' ? ' ' + p.progres + '%' : ''}${p.perubahan ? ' · perlu render' : ''}</span>
      </div>`;
    }).join('');
  } catch (err) { /* server sedang sibuk; coba lagi di putaran berikutnya */ }
}
$('#daftarProyek').addEventListener('click', (e) => { const el = e.target.closest('.proyek'); if (el) bukaDetail(el.dataset.id); });

// ---------------------------------------------------------------- detail proyek
let detailId = null;
let proyekDetail = null;
let detailTanda = '';
let naskahAsli = '';

function tutupDetail() { detailId = null; detailTanda = ''; history.replaceState(null, '', location.pathname); }

async function bukaDetail(id) {
  detailId = id; detailTanda = ''; naskahAsli = '';
  history.replaceState(null, '', '#p=' + id);
  $('#dIsi').innerHTML = '<p class="bantu">Memuat…</p>';
  $('#modalDetail').hidden = false;
  await segarkanDetail();
}

async function segarkanDetail() {
  if (!detailId) return;
  let p;
  try { ({ proyek: p } = await api('/api/proyek/' + detailId)); } catch { return; }
  if (p.id !== detailId) return;
  proyekDetail = p;
  $('#dJudul').textContent = p.meta?.judul || p.nama;
  const tanda = JSON.stringify([p.status, p.selesai, p.hasil, p.galat, p.perubahan, p.link_video, (p.reels || []).map((r) => r.status), p.adegan.map((a) => a.shots.map((s) => [s.pilih, s.siap, s.stiker?.id]))]);
  const naskahBox = $('#dNaskah');
  const naskahDiedit = naskahBox && naskahBox.value !== naskahAsli;
  if (tanda !== detailTanda) {
    detailTanda = tanda;
    const draft = naskahDiedit ? naskahBox.value : null;
    $('#dIsi').innerHTML = htmlDetail(p);
    naskahAsli = p.naskah || '';
    if (draft !== null) $('#dNaskah').value = draft;
  }
  const log = $('#dLog');
  if (log) {
    const bawah = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
    log.textContent = (p.log || []).join('\n');
    if (bawah) log.scrollTop = log.scrollHeight;
  }
  const pesan = $('#dPesan');
  if (pesan) pesan.textContent = p.status === 'jalan' ? `${LANGKAH[p.langkah] || ''} · ${p.pesan} (${p.progres}%)` : '';
}

function labelFormat(o) {
  return o.kembar ? `16:9 + ${o.jumlah_reels || 1} reels` : o.mode === 'teaser' ? '9:16 reels teaser' : o.mode === 'recreate' ? '9:16 re-create' : o.mode === 'ringkas' ? '9:16 ringkasan' : o.format;
}

function htmlDetail(p) {
  const selesai = p.status === 'selesai' && p.hasil?.video;
  const versi = encodeURIComponent(p.log?.length || 0);
  const poster = p.hasil?.thumbnail ? `poster="/hasil/${p.id}/thumbnail?v=${versi}"` : '';
  const v = selesai ? `<video controls preload="metadata" ${poster} src="/hasil/${p.id}/video?v=${versi}"></video>` : '';
  const m = p.meta || {};
  const aksi = [];
  if (selesai) aksi.push('<button data-a="buka-folder">📂 Buka folder hasil</button>', `<a href="/hasil/${p.id}/video" download><button>⬇️ Unduh video</button></a>`);
  if (p.status === 'cek_naskah') aksi.push('<button class="utama" style="width:auto;margin:0" data-a="lanjut">▶️ Naskah oke, lanjut buat video</button>');
  if (['gagal', 'dibatalkan'].includes(p.status)) aksi.push('<button data-a="ulangi">🔁 Coba lagi</button>');
  if (p.status === 'selesai') aksi.push(`<button data-a="ulangi" ${p.perubahan ? 'class="utama" style="width:auto;margin:0"' : ''}>🔁 Render ulang</button>`);
  if ((p.status === 'selesai' || p.status === 'gagal') && p.opsi.mode !== 'bacakan') aksi.push('<button data-a="tulis-ulang" title="Riset, naskah, suara, footage, dan video dibuat ulang dengan gaya cerita yang dipilih di form">✍️ Tulis ulang naskah</button>');
  if (p.status === 'selesai' || p.status === 'gagal') aksi.push('<button data-a="cari-ulang" title="Kata kunci, gambar topik, dan pilihan AI dibuat ulang; naskah & suara tetap">🔎 Cari ulang semua footage</button>');
  if (['jalan', 'antri', 'cek_naskah'].includes(p.status)) aksi.push('<button data-a="batal" class="bahaya">⏹️ Batalkan</button>');
  (p.reels || []).forEach((r, i) => aksi.push(`<button data-buka-proyek="${r.id}" title="${esc(r.sudut || '')}">📱 Reels ${i + 1}${r.status === 'selesai' ? ' ✓' : ''}</button>`));
  if (p.induk) aksi.push(`<button data-buka-proyek="${p.induk}">🖥️ Lihat video panjang</button>`);
  aksi.push('<button data-a="hapus" class="bahaya">🗑️ Hapus proyek</button>');

  const ajakReels = ['teaser', 'recreate'].includes(p.opsi.mode) ? `\n\n▶️ ${p.link_induk ? 'Video lengkapnya: ' + p.link_induk : 'Video lengkapnya ada di channel ini.'}` : '';
  const deskripsi = m.judul ? `${m.judul}\n\n${m.deskripsi}${ajakReels}\n\n${(m.tags || []).map((t) => '#' + t.replace(/\s+/g, '')).join(' ')}` : '';
  return `
    ${p.galat ? `<div class="galat">⚠️ ${esc(p.galat)}</div>` : ''}
    ${p.perubahan ? '<div class="pemberitahuan">Footage sudah diganti. Klik <b>Render ulang</b> kalau sudah selesai mengganti.</div>' : ''}
    ${p.status === 'cek_naskah' ? '<div class="pemberitahuan">Naskah siap. Baca dulu, edit kalau ada yang salah, lalu klik <b>Lanjut</b>.</div>' : ''}
    <p class="bantu" id="dPesan"></p>
    <div class="detail-atas">
      <div>${v || `<div class="meta-box" style="text-align:center;padding:40px">${STATUS[p.status] || p.status}${p.status === 'jalan' ? '…' : ''}</div>`}</div>
      <div>
        <div class="baris">${aksi.join('')}</div>
        ${deskripsi ? `<label class="judul-kolom">Judul, deskripsi & hashtag (deskripsi lengkap + kredit footage ada di deskripsi.txt)</label>
          <div class="meta-box" id="dMeta">${esc(deskripsi)}</div>
          <div class="baris"><button class="kecil" data-salin="dMeta">📋 Salin</button>
          ${selesai ? `<a href="/hasil/${p.id}/deskripsi" target="_blank"><button class="kecil">📄 deskripsi.txt</button></a>` : ''}</div>` : ''}
        ${p.riset?.length ? `<p class="bantu">Riset: ${p.riset.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.judul)}</a>`).join(', ')}</p>` : ''}
      </div>
    </div>
    ${p.naskah ? `<label class="judul-kolom" for="dNaskah">Naskah (${p.naskah.split(/\s+/).length} kata)</label>
      <textarea id="dNaskah" rows="10">${esc(p.naskah)}</textarea>
      <div class="baris"><button data-a="naskah">💾 Simpan naskah & buat ulang video</button>
      <span class="bantu">Suara, adegan, dan footage dibuat ulang mengikuti naskah baru.</span></div>` : ''}
    ${p.adegan?.length ? `<details ${p.status === 'selesai' ? 'open' : ''}><summary>Adegan & footage (${p.adegan.length} adegan) — ganti gambar yang kurang pas</summary>
      ${p.adegan.map((a, ia) => htmlAdegan(a, ia)).join('')}</details>` : ''}
    ${p.opsi.kembar ? `<details ${p.status === 'selesai' && !p.link_video ? 'open' : ''}><summary>📱 Reels dari video ini & link video panjang</summary>
      ${(p.reels || []).length ? `<ol class="bantu">${p.reels.map((r) => `<li><a href="#" data-buka-proyek="${r.id}">${esc(r.nama)}</a> — ${esc(STATUS[r.status] || r.status)}<br>Fokus: ${esc(r.sudut || '-')}</li>`).join('')}</ol>`
        : '<p class="bantu">Reels dibuat otomatis setelah naskah video ini jadi.</p>'}
      <label class="judul-kolom" for="dLink">Link video panjang (setelah diupload)</label>
      <input id="dLink" type="url" placeholder="https://youtu.be/…" value="${esc(p.link_video || '')}">
      <div class="baris"><button data-a="link">🔗 Pasang di deskripsi semua reels</button></div>
      <p class="bantu">deskripsi.txt tiap reels langsung diperbarui, tanpa render ulang. Untuk YouTube Shorts, pilih juga
        video panjang ini sebagai <b>Video terkait</b> di YouTube Studio supaya link-nya tampil di bawah reels.</p>
    </details>` : ''}
    ${p.recreate ? `<p class="bantu">♻️ Re-create dari: <b>${esc(p.recreate.sumber?.nama || '')}</b> · gaya ${p.recreate.gaya_short === 'mandiri' ? 'mandiri' : 'teaser'}${p.recreate.izin && p.suara_ref ? ' · warna suara disamakan dengan sumber' : ''}</p>` : ''}
    ${['teaser', 'recreate'].includes(p.opsi.mode) ? `<details><summary>${p.recreate ? 'Tema short ini' : 'Fokus reels ini'} (untuk ✍️ Tulis ulang)</summary>
      <p class="bantu">Bagian video panjang yang dijadikan short, misalnya satu bukti atau kejanggalan tertentu.</p>
      <textarea id="dSudut" rows="3">${esc(p.recreate ? (p.recreate.tema || '') : (p.sudut || ''))}</textarea>
      <div class="baris"><button data-a="tulis-ulang">✍️ Tulis ulang reels ini dengan fokus ini</button></div>
    </details>` : ''}
    ${!['bacakan', 'teaser'].includes(p.opsi.mode) ? `<details><summary>Topik & arahan cerita (untuk ✍️ Tulis ulang naskah)</summary>
      <p class="bantu">Tulis sudut pandang yang kamu mau, misalnya: hubungkan dengan kondisi di bulan dan tempat di Bumi
        yang mirip; twist di akhir: mungkin dokumentasinya dibuat ulang di studio. AI tetap menyajikan teori sebagai teori.</p>
      <textarea id="dArahan" rows="4">${esc(p.sumber_teks)}</textarea>
      <div class="baris"><button data-a="tulis-ulang">✍️ Tulis ulang naskah dengan arahan ini</button></div>
    </details>` : ''}
    <details><summary>Disclaimer video ini</summary>
      <select id="dDisclaimer">${[['awal', 'Teks di awal video (5 detik)'], ['akhir', 'Kartu di akhir, dibacakan'], ['keduanya', 'Keduanya'], ['tidak', 'Tanpa disclaimer']]
        .map(([v, t]) => `<option value="${v}" ${p.opsi.disclaimer === v ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <textarea id="dTeksDisclaimer" rows="2" style="margin-top:8px">${esc(p.opsi.teks_disclaimer)}</textarea>
      <div class="baris"><button data-a="disclaimer">✅ Terapkan & render ulang</button></div>
    </details>
    <details><summary>Suara narator video ini</summary>
      <select id="dSuara">${Object.entries(statusTerakhir?.suara || {})
        .map(([v, t]) => `<option value="${esc(v)}" ${p.opsi.suara === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>
      <div class="baris"><button data-a="ganti-suara" title="Naskah tetap; narasi dibacakan ulang, footage disesuaikan dengan waktu suara baru, lalu dirender ulang">✅ Bacakan ulang dengan suara ini</button></div>
    </details>
    <details><summary>Log proses</summary><div class="log" id="dLog"></div></details>
    <p class="bantu">Opsi: ${esc(labelFormat(p.opsi))} · ${p.opsi.mode === 'tulis' ? Math.round(p.opsi.durasi / 60 * 10) / 10 + ' menit · ' : ''} ${esc(p.opsi.suara)} ${p.opsi.kecepatan}% · subtitle ${p.opsi.subtitle ? 'ya' : 'tidak'} · musik ${p.opsi.musik ? 'ya' : 'tidak'} · AI cek gambar ${p.opsi.cek_gambar ? 'ya' : 'tidak'} · visual ${p.opsi.visual === 'klasik' ? 'klasik' : 'video + stiker'} · gaya ${esc(p.opsi.gaya)}${p.opsi.maskot ? ' + maskot' : ''} · disclaimer ${esc(p.opsi.disclaimer)}</p>`;
}

function htmlAdegan(a, ia) {
  const shots = a.shots.map((s, js) => {
    if (s.banding) {  // perbandingan dua foto berdampingan
      const g = (x) => x.thumb ? `style="background-image:url('${esc(x.thumb)}');flex:1"` : 'style="flex:1"';
      return `<div class="shot"><div class="gbr" style="display:flex;gap:2px;background:#000">
        <div ${g(s.banding.kiri)} class="gbr"></div><div ${g(s.banding.kanan)} class="gbr"></div></div>
        <div class="ket">🆚 ${esc(s.banding.kiri.label)} vs ${esc(s.banding.kanan.label)}</div></div>`;
    }
    const k = s.kandidat;
    const st = s.stiker;
    const gbr = k?.thumb ? `style="background-image:url('${esc(k.thumb)}')"` : '';
    const ket = (k ? `${esc(k.sumber)} · ${k.jenis === 'video' ? '🎞️' : '🖼️'} ${(s.frames / 30).toFixed(1)} dtk${k.skor_ai != null ? ` · AI ${k.skor_ai}/10` : ''}${k.isi_ai ? `<br>${esc(k.isi_ai)}` : ''}` : 'latar gelap')
      + (st ? `<br>🏷️ stiker: ${esc(st.isi_ai || st.judul || st.sumber)}` : '');
    return `<div class="shot">
      <div class="gbr" ${gbr}>${gbr ? '' : (k ? esc(k.sumber) : '—')}${st?.thumb ? `<div class="stiker" style="background-image:url('${esc(st.thumb)}')" title="Stiker foto di atas footage"></div>` : ''}</div>
      <div class="ket">${ket}</div>
      <div class="aksi">
        <button data-ganti="${ia},${js}" title="Pakai kandidat berikutnya">🔄 Ganti</button>
        <button data-alt="${ia},${js}" title="Pilih dari kandidat lain">🖼️ Pilih</button>
        <label title="Pakai foto/video sendiri">📁<input type="file" accept="image/*,video/*" data-upload="${ia},${js}" hidden></label>
        ${k?.halaman ? `<a href="${esc(k.halaman)}" target="_blank" rel="noopener"><button title="Lihat sumber">↗</button></a>` : ''}
        ${st ? `<button data-hapus-stiker="${ia},${js}" title="Buang stiker dari shot ini (berlaku setelah Render ulang)">✖ Stiker</button>` : ''}
      </div></div>`;
  }).join('');
  return `<div class="adegan" data-ia="${ia}">
    <div class="teks-adegan"><b>${ia + 1}.</b> ${esc(a.teks)} <span class="kecil">(${(a.durasi || 0).toFixed(1)} dtk)</span></div>
    <div class="q">🔎 ${esc(a.q?.a || '-')} / ${esc(a.q?.b || '-')}</div>
    <div class="shots">${shots}</div>
    <div class="alternatif" id="alt-${ia}" hidden>${a.alternatif.map((k) => `<div data-pilih="${ia},${k.index}" title="${esc((k.isi_ai || k.judul || k.sumber) + (k.skor_ai != null ? ' · AI ' + k.skor_ai + '/10' : ''))}" style="background-image:url('${esc(k.thumb || '')}')"><span>${esc(k.sumber)}${k.jenis === 'video' ? ' 🎞️' : ''}</span></div>`).join('') || '<p class="bantu">Tidak ada kandidat lain.</p>'}</div>
  </div>`;
}

let shotUntukAlt = {};
$('#dIsi').addEventListener('click', async (e) => {
  const t = e.target.closest('[data-a],[data-ganti],[data-alt],[data-pilih],[data-salin],[data-buka-proyek],[data-hapus-stiker]');
  if (!t || !detailId) return;
  const id = detailId;
  if (t.dataset.bukaProyek) { e.preventDefault(); bukaDetail(t.dataset.bukaProyek); return; }
  try {
    if (t.dataset.salin) {
      await navigator.clipboard.writeText($('#' + t.dataset.salin).textContent);
      t.textContent = '✓ Tersalin';
      return;
    }
    if (t.dataset.a) {
      const a = t.dataset.a;
      if (a === 'hapus' && !confirm('Hapus proyek ini? (Video yang sudah jadi di folder output tetap ada.)')) return;
      if (a === 'cari-ulang' && !confirm('Cari ulang semua footage untuk video ini? AI akan memilih gambar lagi (bisa 1-2 menit per adegan). Footage yang kamu ganti manual ikut diganti.')) return;
      let body = a === 'naskah' ? { naskah: $('#dNaskah').value } : {};
      let jalur = a;
      if (a === 'tulis-ulang') {
        const p = proyekDetail || {};
        const gaya = $('#gaya_naskah').selectedOptions[0].text;
        if (['teaser', 'recreate'].includes(p.opsi?.mode)) {
          if (!confirm('Tulis ulang naskah reels ini dengan fokus yang tertulis? Suara, footage, dan video reels dibuat ulang.')) return;
          body = { opsi: { gaya_naskah: p.opsi.gaya_naskah }, sudut: $('#dSudut') ? $('#dSudut').value : '' };
        } else {
          const reels = p.opsi?.kembar ? ` Reels ikut dibuat ulang: ${$('#jumlah_reels').value} × ±${$('#durasi_reels').value} detik.` : '';
          if (!confirm('Tulis ulang naskah video ini dari awal dengan gaya cerita "' + gaya + '"? Semua (riset, suara, footage) dibuat ulang.' + reels)) return;
          body = { opsi: { gaya_naskah: $('#gaya_naskah').value, cta: $('#cta').value.trim(), jumlah_reels: +$('#jumlah_reels').value,
                           durasi_reels: +$('#durasi_reels').value, cta_reels: $('#cta_reels').value.trim() },
                   teks: $('#dArahan') ? $('#dArahan').value : '' };
        }
        jalur = 'tulis-ulang';
      }
      if (a === 'link') body = { link: $('#dLink').value.trim() };
      if (a === 'ganti-suara') {
        jalur = 'ulangi';
        body = { opsi: { suara: $('#dSuara').value } };
      }
      if (a === 'disclaimer') {
        jalur = 'ulangi';
        body = { opsi: { disclaimer: $('#dDisclaimer').value, teks_disclaimer: $('#dTeksDisclaimer').value.trim() } };
      }
      t.disabled = true;
      await api(`/api/proyek/${id}/${jalur}`, { body });
      if (a === 'hapus') { $('#modalDetail').hidden = true; tutupDetail(); }
      if (a === 'naskah') naskahAsli = $('#dNaskah').value;
    } else if (t.dataset.ganti) {
      const [ia, js] = t.dataset.ganti.split(',').map(Number);
      t.disabled = true;
      await api(`/api/proyek/${id}/pilih`, { body: { adegan: ia, shot: js } });
    } else if (t.dataset.hapusStiker) {
      const [ia, js] = t.dataset.hapusStiker.split(',').map(Number);
      t.disabled = true;
      await api(`/api/proyek/${id}/hapus-stiker`, { body: { adegan: ia, shot: js } });
    } else if (t.dataset.alt) {
      const [ia, js] = t.dataset.alt.split(',').map(Number);
      shotUntukAlt[ia] = js;
      const box = $('#alt-' + ia);
      box.hidden = !box.hidden;
      return;
    } else if (t.dataset.pilih) {
      const [ia, index] = t.dataset.pilih.split(',').map(Number);
      await api(`/api/proyek/${id}/pilih`, { body: { adegan: ia, shot: shotUntukAlt[ia] ?? 0, index } });
    }
    detailTanda = '';
    await segarkanDetail();
    muatDaftar();
  } catch (err) { alert('Gagal: ' + err.message); t.disabled = false; }
});
$('#dIsi').addEventListener('change', async (e) => {
  const inp = e.target.closest('[data-upload]');
  if (!inp || !inp.files[0]) return;
  const [ia, js] = inp.dataset.upload.split(',');
  const fd = new FormData();
  fd.append('file', inp.files[0]); fd.append('adegan', ia); fd.append('shot', js);
  try { await api(`/api/proyek/${detailId}/upload-footage`, { body: fd }); } catch (err) { alert('Gagal: ' + err.message); }
  detailTanda = '';
  segarkanDetail();
});

// ---------------------------------------------------------------- ide topik
let bankIde = {};
let urutanKategori = [];
let kategoriAktif = '';
const ideAI = {};          // kategori → ide tambahan dari AI
const ideTerpilih = new Set();

async function bukaIde() {
  if (!urutanKategori.length) ({ ide: bankIde, urutan: urutanKategori } = await api('/api/ide'));
  kategoriAktif = kategoriAktif || urutanKategori[0];
  gambarIde();
  $('#modalIde').hidden = false;
}

function gambarIde() {
  $('#ideKategori').innerHTML = urutanKategori.map((k) =>
    `<button data-kat="${esc(k)}" class="${k === kategoriAktif ? 'aktif' : ''}">${esc(k)}</button>`).join('');
  const daftar = [...(ideAI[kategoriAktif] || []).map((t) => [t, true]), ...bankIde[kategoriAktif].map((t) => [t, false])];
  $('#ideDaftar').innerHTML = daftar.map(([t, baru]) =>
    `<label class="ide ${baru ? 'baru' : ''}" title="${baru ? 'Ide dari AI — cek dulu topiknya' : ''}">
      <input type="checkbox" data-ide="${esc(t)}" ${ideTerpilih.has(t) ? 'checked' : ''}>
      <span data-pakai="${esc(t)}">${baru ? '🤖 ' : ''}${esc(t)}</span></label>`).join('');
  $('#btnIdeAntri').disabled = !ideTerpilih.size;
  $('#btnIdeAntri').textContent = `🎬 Antrikan yang dicentang${ideTerpilih.size ? ` (${ideTerpilih.size})` : ''}`;
}

$('#btnIde').addEventListener('click', () => bukaIde().catch((err) => alert('Gagal: ' + err.message)));
$('#ideKategori').addEventListener('click', (e) => {
  const b = e.target.closest('[data-kat]');
  if (b) { kategoriAktif = b.dataset.kat; gambarIde(); }
});
$('#ideDaftar').addEventListener('click', (e) => {
  const pakai = e.target.closest('[data-pakai]');
  if (pakai) {  // klik teks = pakai ide ini di form
    e.preventDefault();
    form.mode = 'tulis'; pilihSeg('#segMode', 'tulis'); ubahMode();
    $('#teks').value = pakai.dataset.pakai;
    $('#modalIde').hidden = true;
    $('#teks').focus();
  }
});
$('#ideDaftar').addEventListener('change', (e) => {
  const c = e.target.closest('[data-ide]');
  if (!c) return;
  if (c.checked) ideTerpilih.add(c.dataset.ide); else ideTerpilih.delete(c.dataset.ide);
  gambarIde();
});
$('#btnIdeAI').addEventListener('click', async () => {
  const b = $('#btnIdeAI');
  b.disabled = true;
  $('#ideInfo').textContent = '⏳ AI sedang berpikir (±1-3 menit, lebih lama kalau ada video yang sedang diproses)…';
  try {
    const kat = kategoriAktif;
    const { ide, dibuang } = await api('/api/ide', { body: { kategori: kat, hindari: ideAI[kat] || [] } });
    ideAI[kat] = [...ide.map((x) => x.judul), ...(ideAI[kat] || [])];
    $('#ideInfo').textContent = `✓ ${ide.length} ide baru (bertanda 🤖), semuanya punya artikel Wikipedia`
      + (dibuang ? ` · ${dibuang} ide dibuang karena topiknya tidak ditemukan (kemungkinan dikarang AI).` : '.');
    if (kat === kategoriAktif) gambarIde();
  } catch (err) { $('#ideInfo').textContent = 'Gagal: ' + err.message; }
  b.disabled = false;
});
$('#btnIdeAntri').addEventListener('click', async () => {
  const topik = [...ideTerpilih];
  if (!topik.length) return;
  try {
    const opsi = { ...opsiForm(), mode: 'tulis' };
    const r = await api('/api/proyek', { body: { teks: topik.join('\n'), opsi, per_baris: true } });
    ideTerpilih.clear();
    $('#ideInfo').textContent = `✓ ${r.id.length} video masuk antrian.`;
    gambarIde();
    muatDaftar();
  } catch (err) { $('#ideInfo').textContent = 'Gagal: ' + err.message; }
});

// ---------------------------------------------------------------- mulai
(async () => {
  try {
    const s = await muatStatus();
    isiForm(s.config.default, s.suara);
  } catch (err) {
    $('#chip').innerHTML = `<span class="chip no">Server tidak merespons: ${esc(err.message)}</span>`;
  }
  muatDaftar();
  const dariAlamat = location.hash.match(/^#p=([\w-]+)/);
  if (dariAlamat) bukaDetail(dariAlamat[1]);
  if (location.hash === '#ide') bukaIde();
  setInterval(muatDaftar, 2500);
  setInterval(segarkanDetail, 2500);
  setInterval(muatStatus, 30000);
})();
