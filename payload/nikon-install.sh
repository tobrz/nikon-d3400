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
chmod 755 /opt/nikon-d3400/bootstrap.sh /opt/nikon-d3400/nikon-install.sh /opt/nikon-d3400/app/server.py /opt/nikon-d3400/app/wifi_bringup.py || true

if [ -f "$BOOT/nikon-wifi.json" ]; then
  cp "$BOOT/nikon-wifi.json" /var/lib/nikon-d3400/wifi.json
fi

cp /opt/nikon-d3400/units/*.service /etc/systemd/system/
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
systemctl enable nikon-bootstrap.service nikon-wifi.service nikon-d3400.service
systemctl start nikon-d3400.service || true
systemctl start nikon-wifi.service || true
systemctl start nikon-bootstrap.service || true

if [ ! -f /var/lib/nikon-d3400/first-reboot-done ]; then
  touch /var/lib/nikon-d3400/first-reboot-done
  systemd-run --unit=nikon-first-reboot --on-active=25s /sbin/reboot || true
fi
echo "install script finished"
