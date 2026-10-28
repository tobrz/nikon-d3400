#!/bin/bash
# Share the pictures folder so a Mac can open it and drag files into Photos.
# The share is read-only. Login is the Linux user "camera".
set -u
SHOTS=/var/lib/nikon-d3400/shots
MARK="# nikon-d3400 shots share"
CONF=/etc/samba/smb.conf

mkdir -p "$SHOTS"
chmod 755 "$SHOTS" || true

if ! command -v smbd >/dev/null; then
  if ! command -v apt-get >/dev/null; then
    echo "samba not installed"
    exit 0
  fi
  if ! ip route | grep -q '^default'; then
    echo "samba skipped, no route to install it"
    exit 0
  fi
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y samba || {
    echo "samba install failed"
    exit 0
  }
fi
if ! command -v smbd >/dev/null; then
  echo "samba not installed"
  exit 0
fi

if [ -f "$CONF" ] && ! grep -q "$MARK" "$CONF"; then
  cat >> "$CONF" << 'EOF'

# nikon-d3400 shots share
[shots]
   comment = Nikon D3400 pictures
   path = /var/lib/nikon-d3400/shots
   browseable = yes
   read only = yes
   guest ok = no
   valid users = camera
   force user = root
EOF
fi

if command -v pdbedit >/dev/null && ! pdbedit -L 2>/dev/null | grep -q '^camera:'; then
  printf '%s\n%s\n' 'nikon-d3400' 'nikon-d3400' | smbpasswd -a -s camera || echo "smb password skipped"
fi

mkdir -p /etc/avahi/services
cat > /etc/avahi/services/nikon-shots.service << 'EOF'
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">%h pictures</name>
  <service>
    <type>_smb._tcp</type>
    <port>445</port>
  </service>
</service-group>
EOF

systemctl enable smbd nmbd 2>/dev/null || true
systemctl restart smbd nmbd 2>/dev/null || true
systemctl try-restart avahi-daemon 2>/dev/null || true
echo "shots share ready at smb://nikon-d3400.local/shots"
