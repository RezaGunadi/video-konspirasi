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
cat > "$HOME/.config/systemd/user/video-ai.service" <<EOF
[Unit]
Description=Video Konspirasi AI (pekerja mini PC)
After=network-online.target

[Service]
WorkingDirectory=$APP
Environment=VIDEO_AI_LAN=1
Environment=PYTHONUNBUFFERED=1
ExecStartPre=-/usr/bin/git -C $APP pull --ff-only --quiet
ExecStart=$APP/.venv/bin/python app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now video-ai.service
sleep 3
systemctl --user --no-pager --lines=5 status video-ai.service || true
echo "UI: http://$(hostname -I | awk '{print $1}'):3220"
