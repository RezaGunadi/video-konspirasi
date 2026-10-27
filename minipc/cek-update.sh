#!/bin/sh
# Dijalankan timer video-ai-update tiap menit. Ada kode Python baru di GitHub → aplikasi langsung direstart: proyek
# yang sedang jalan dibatalkan lalu mengulang langkahnya dengan logika baru, jadi tidak ada video yang terlanjur
# dibuat dengan kode lama. Perubahan lain (README dll.) cukup ditarik tanpa restart.
cd "$(dirname "$0")/.." || exit 0
git fetch --quiet origin 2>/dev/null || exit 0
# Tidak ada yang baru di GitHub. Termasuk saat mini PC lebih maju (kode dikirim langsung lewat LAN): dulu selisihnya
# terbaca sebagai "kode baru" dan aplikasi direstart tiap menit.
git merge-base --is-ancestor '@{u}' HEAD && exit 0
berubah=$(git diff --name-only HEAD '@{u}')
git pull --ff-only --quiet || exit 0
echo "$berubah" | grep -qx requirements.txt && .venv/bin/pip install -q -r requirements.txt
if echo "$berubah" | grep -qE '\.py$|^requirements\.txt$'; then
  echo "Kode baru $(git log --oneline -1) → restart video-ai"
  systemctl --user restart video-ai.service
fi
