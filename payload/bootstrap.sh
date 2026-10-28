#!/bin/bash
# Retries until gphoto2 is installed. Ethernet on the first boot is enough.
set -u
LOG=/var/lib/nikon-d3400/bootstrap.log
mkdir -p /var/lib/nikon-d3400
exec >>"$LOG" 2>&1
echo "---- $(date) ----"
if ! command -v gphoto2 >/dev/null || ! command -v git >/dev/null || ! command -v smbd >/dev/null; then
  if ! ip route | grep -q '^default'; then
    if ! command -v gphoto2 >/dev/null || ! command -v git >/dev/null; then
      echo "No default route yet. Plug in ethernet."
      exit 1
    fi
  else
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y gphoto2 avahi-daemon git samba
  fi
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
  ready=0
  for _ in 1 2 3 4 5 6; do
    if ollama list >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 5
  done
  if [ "$ready" -eq 1 ]; then
    ollama pull qwen2.5:0.5b || echo "model pull skipped"
  else
    echo "model pull skipped"
  fi
fi
if [ -x /opt/nikon-d3400/samba-setup.sh ]; then
  /opt/nikon-d3400/samba-setup.sh || echo "samba share skipped"
fi
echo "ready"
