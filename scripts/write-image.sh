#!/bin/bash
# Write a headless Nikon D3400 image onto an external SD card.
# Usage: scripts/write-image.sh disk5
set -euo pipefail
DISK="${1:-}"
if [ -z "$DISK" ]; then
  echo "Usage: $0 disk5" >&2
  exit 1
fi
if [ "$DISK" = "disk0" ] || [ "$DISK" = "disk3" ]; then
  echo "Refusing to write the internal disk." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${HOME}/Library/Caches/nikon-d3400"
IMAGE_NAME="2026-10-06-raspios-trixie-arm64-lite.img.xz"
IMAGE_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/${IMAGE_NAME}"
mkdir -p "$CACHE"
cd "$CACHE"
if [ ! -f "$IMAGE_NAME" ]; then
  curl -fL --retry 2 -O "$IMAGE_URL"
  curl -fL --retry 2 -O "${IMAGE_URL}.sha256"
fi
shasum -a 256 -c "${IMAGE_NAME}.sha256"

INFO="$(diskutil info "$DISK")"
echo "$INFO" | grep -q "Device Location:.*External" || { echo "$DISK is not external." >&2; exit 1; }
echo "$INFO" | grep -q "64\." || echo "Warning: expected about 64 GB."

echo "Unmounting $DISK"
diskutil unmountDisk "$DISK"
echo "Writing image. This replaces everything on $DISK."
xz -dc "$CACHE/$IMAGE_NAME" | sudo dd of="/dev/r${DISK}" bs=4m status=progress
sync
sleep 3
diskutil mountDisk "$DISK" || true
sleep 2

BOOT=""
for candidate in /Volumes/bootfs /Volumes/boot; do
  if [ -d "$candidate" ] && [ -f "$candidate/cmdline.txt" -o -f "$candidate/config.txt" ]; then
    BOOT="$candidate"
    break
  fi
done
if [ -z "$BOOT" ]; then
  echo "Image written, but the boot volume did not mount. Plug the card back in and copy payload by hand." >&2
  exit 1
fi

rm -rf "$BOOT/nikon-d3400"
mkdir -p "$BOOT/nikon-d3400"
cp -R "$ROOT/payload/." "$BOOT/nikon-d3400/"
# The installer also lives at the boot root, which is /boot/firmware on the Pi.
cp "$ROOT/payload/nikon-install.sh" "$BOOT/nikon-install.sh"

HASH="$(openssl passwd -6 'nikon-d3400')"
python3 - "$BOOT/user-data" "$HASH" << 'PY'
import sys
path, hashed = sys.argv[1], sys.argv[2]
open(path, "w").write(f"""#cloud-config
hostname: nikon-d3400
manage_etc_hosts: true
timezone: America/Chicago
locale: en_US.UTF-8
keyboard:
  model: pc105
  layout: us
users:
  - name: camera
    groups: [adm, dialout, cdrom, sudo, audio, video, plugdev, users, netdev, input, gpio, spi, i2c, render]
    shell: /bin/bash
    lock_passwd: false
    passwd: "{hashed}"
enable_ssh: true
ssh_pwauth: true
runcmd:
  - [bash, /boot/firmware/nikon-install.sh]
""")
PY
printf 'instance-id: nikon-d3400\n' > "$BOOT/meta-data"
touch "$BOOT/ssh"

if ! grep -q 'nikon-d3400 usb host' "$BOOT/config.txt"; then
  cat >> "$BOOT/config.txt" << 'EOF'

# nikon-d3400 usb host
[pi02]
dtoverlay=dwc2,dr_mode=host
[all]
EOF
fi

sync
echo "Boot volume ready at $BOOT"
echo "First boot: ethernet plugged in, no keyboard, no HDMI, no camera."
echo "When Wi-Fi Nikon-D3400 appears, open http://192.168.50.1"
echo "Password: nikon-d3400"
