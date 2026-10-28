#!/bin/bash
# Retries until gphoto2 is installed. Ethernet on the first boot is enough.
set -u
LOG=/var/lib/nikon-d3400/bootstrap.log
mkdir -p /var/lib/nikon-d3400
exec >>"$LOG" 2>&1
echo "---- $(date) ----"
if ! command -v gphoto2 >/dev/null || ! command -v git >/dev/null; then
  if ! ip route | grep -q '^default'; then
    echo "No default route yet. Plug in ethernet."
    exit 1
  fi
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y gphoto2 avahi-daemon git
fi
if ! command -v gphoto2 >/dev/null; then
  echo "gphoto2 still missing"
  exit 1
fi
# A half-gigabyte model only on boards that can hold it. The written guide works without it.
MEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "$MEM_KB" -ge 2000000 ] && ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh || echo "ollama install skipped"
fi
if command -v ollama >/dev/null; then
  systemctl enable --now ollama || true
  ollama pull qwen2.5:0.5b || echo "model pull skipped"
fi
echo "ready"
