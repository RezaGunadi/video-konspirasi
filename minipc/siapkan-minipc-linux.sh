#!/usr/bin/env bash
# Siapkan mini PC (Linux) untuk Video Konspirasi AI: SSH dari laptop (pakai kunci, tanpa password),
# firewall hanya untuk jaringan lokal, lalu tampilkan info CPU/RAM/IP. Tidak memasang apa pun selain OpenSSH.
# Jalankan di terminal mini PC:
#   curl -fsSL https://raw.githubusercontent.com/RezaGunadi/video-konspirasi/main/minipc/siapkan-minipc-linux.sh | sudo bash
set -euo pipefail
KUNCI='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG/IlR6oiwlNiYkmuqGWR1IVMJ869ht+N/+GtufOKDpI video-konspirasi-laptop'
PENGGUNA="${SUDO_USER:-$(logname 2>/dev/null || whoami)}"
GRUP="$(id -gn "$PENGGUNA")"
RUMAH="$(getent passwd "$PENGGUNA" | cut -d: -f6)"

echo "1/4 Memasang OpenSSH server..."
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q openssh-server
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm openssh
  fi
fi
systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd

echo "2/4 Memasang kunci akses laptop untuk pengguna $PENGGUNA..."
install -d -m 700 -o "$PENGGUNA" -g "$GRUP" "$RUMAH/.ssh"
touch "$RUMAH/.ssh/authorized_keys"
grep -qF "$KUNCI" "$RUMAH/.ssh/authorized_keys" || echo "$KUNCI" >> "$RUMAH/.ssh/authorized_keys"
chown "$PENGGUNA:$GRUP" "$RUMAH/.ssh/authorized_keys"
chmod 600 "$RUMAH/.ssh/authorized_keys"

echo "3/4 Firewall: SSH (22) dan Ollama (11434) hanya dari jaringan lokal..."
JARINGAN="$(ip route | awk '/proto kernel/ && /scope link/ {print $1; exit}')"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow from "$JARINGAN" to any port 22 proto tcp >/dev/null
  ufw allow from "$JARINGAN" to any port 11434 proto tcp >/dev/null
fi

echo "4/4 Info mini PC (kirim baris hijau di bawah ini ke Claude):"
CPU="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ *//')"
RAM="$(free -g | awk '/^Mem:/ {print $2 " GB total, " $7 " GB bebas"}')"
IP="$(hostname -I | xargs)"
OS="$(. /etc/os-release && echo "$PRETTY_NAME")"
echo ""
printf '\033[1;32mNama: %s | User: %s | OS: %s | CPU: %s | RAM: %s | IP: %s\033[0m\n' \
  "$(hostname)" "$PENGGUNA" "$OS" "$CPU" "$RAM" "$IP"
