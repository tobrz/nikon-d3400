#!/bin/bash
# First boot, run by cloud-init. Headless: no keyboard and no HDMI.
# Log stays on the boot partition so it can be read from a Mac if setup fails.
set -u
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot
LOG="$BOOT/nikon-install.log"
mkdir -p /var/lib/nikon-d3400
exec > >(tee -a "$LOG") 2>&1
echo "---- $(date -Is) nikon-install ----"

for unit in digipi digipi-setup hostapd; do
  systemctl disable --now "$unit" 2>/dev/null || true
done

hostnamectl set-hostname nikon-d3400 || true
if ! grep -q 'nikon-d3400' /etc/hosts; then
  echo "127.0.1.1 nikon-d3400" >> /etc/hosts
fi

mkdir -p /opt/nikon-d3400 /var/lib/nikon-d3400/shots
rm -rf /opt/nikon-d3400/app /opt/nikon-d3400/units
cp -a "$BOOT/nikon-d3400/." /opt/nikon-d3400/
chmod 755 /opt/nikon-d3400/bootstrap.sh /opt/nikon-d3400/nikon-install.sh /opt/nikon-d3400/samba-setup.sh /opt/nikon-d3400/app/server.py /opt/nikon-d3400/app/wifi_bringup.py || true

# A dirty FAT card can leave the web unit renamed FSCK0000.000. Put it back
# before enable, or the page never starts and the git update button is unreachable.
restore_unit() {
  local dir="$1"
  local orphan
  [ -d "$dir" ] || return 0
  for orphan in "$dir"/FSCK*.000; do
    [ -f "$orphan" ] || continue
    if grep -q 'server.py' "$orphan"; then
      cp "$orphan" "$dir/nikon-d3400.service"
    fi
  done
}
restore_unit "$BOOT/nikon-d3400/units"
restore_unit /opt/nikon-d3400/units

if [ -f "$BOOT/nikon-wifi.json" ]; then
  cp "$BOOT/nikon-wifi.json" /var/lib/nikon-d3400/wifi.json
fi
if [ -f "$BOOT/nikon-revision" ] && [ ! -f /var/lib/nikon-d3400/revision ]; then
  cp "$BOOT/nikon-revision" /var/lib/nikon-d3400/revision
fi

mkdir -p /etc/systemd/system
for unit in /opt/nikon-d3400/units/*.service; do
  [ -f "$unit" ] || continue
  cp "$unit" /etc/systemd/system/
done
systemctl daemon-reload

if command -v raspi-config >/dev/null; then
  raspi-config nonint do_wifi_country US || true
fi
rfkill unblock wifi || true

if [ -f "$BOOT/config.txt" ] && ! grep -q 'nikon-d3400 usb host' "$BOOT/config.txt"; then
  cat >> "$BOOT/config.txt" << 'EOF'

# nikon-d3400 usb host
[pi02]
dtoverlay=dwc2,dr_mode=host
[all]
EOF
fi

systemctl enable ssh || true
for unit in nikon-bootstrap.service nikon-wifi.service nikon-d3400.service; do
  systemctl enable "$unit" || true
  systemctl start "$unit" || true
done

if [ ! -f /var/lib/nikon-d3400/first-reboot-done ]; then
  touch /var/lib/nikon-d3400/first-reboot-done
  systemd-run --unit=nikon-first-reboot --on-active=25s /sbin/reboot || true
fi
echo "install script finished"
