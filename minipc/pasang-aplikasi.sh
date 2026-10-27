#!/usr/bin/env bash
# Pasang / perbarui Video Konspirasi AI di mini PC Linux sebagai pengguna biasa (tanpa sudo):
# repo dari GitHub, venv Python, paket (torch versi CPU), lalu service systemd --user "video-ai" yang:
#   - menarik update dari GitHub setiap kali start (semua PC selalu versi yang sama),
#   - membuka UI di LAN (http://<IP mini PC>:3220) supaya bisa dipantau dari laptop.
# Butuh paket sistem python3-venv dan "loginctl enable-linger" (dipasang skrip root tahap 2).
set -euo pipefail
REPO="https://github.com/RezaGunadi/video-konspirasi.git"
APP="$HOME/video-konspirasi"

if [ -d "$APP/.git" ]; then
  git -C "$APP" pull --ff-only --quiet
else
  git clone --quiet "$REPO" "$APP"
fi
cd "$APP"
mkdir -p "$HOME/tools/hf-cache" "$HOME/tools/openvoice"

[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
# torch CPU (±200 MB) untuk OpenVoice (suara saya) & foto 2.5D; versi CUDA tidak perlu di mini PC
.venv/bin/pip install -q --index-url https://download.pytorch.org/whl/cpu torch
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$HOME/.config/systemd/user"
# Service --user tidak bisa menunggu network-online.target milik sistem: setelah mati lampu, pull jalan sebelum
# DNS siap ("Could not resolve host") dan mini PC tetap memakai kode lama. Jadi pull dicoba ulang sampai ±60 detik.
cat > "$HOME/.config/systemd/user/video-ai.service" <<EOF
[Unit]
Description=Video Konspirasi AI (pekerja mini PC)

[Service]
WorkingDirectory=$APP
Environment=VIDEO_AI_LAN=1
Environment=PYTHONUNBUFFERED=1
ExecStartPre=-/bin/sh -c 'for coba in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do /usr/bin/git -C $APP pull --ff-only --quiet && exit 0; sleep 3; done; exit 1'
ExecStart=$APP/.venv/bin/python app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
# Kode baru tidak menunggu proyek selesai: timer tiap menit menarik update dan merestart aplikasi (minipc/cek-update.sh).
cat > "$HOME/.config/systemd/user/video-ai-update.service" <<EOF
[Unit]
Description=Tarik kode baru Video AI, restart kalau logikanya berubah

[Service]
Type=oneshot
ExecStart=/bin/sh $APP/minipc/cek-update.sh
EOF
cat > "$HOME/.config/systemd/user/video-ai-update.timer" <<EOF
[Unit]
Description=Cek kode baru Video AI tiap menit

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now video-ai.service
systemctl --user enable --now video-ai-update.timer
sleep 3
systemctl --user --no-pager --lines=5 status video-ai.service || true
echo "UI: http://$(hostname -I | awk '{print $1}'):3220"
