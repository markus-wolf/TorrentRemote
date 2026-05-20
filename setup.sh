#!/usr/bin/env bash
# TorrentRemote — Ubuntu server setup
# Run as root:  sudo bash setup.sh
set -euo pipefail

TORRENT_USER="qbittorrent"
DOWNLOAD_DIR="/downloads"
VPN_IFACE="nordlynx"          # NordVPN NordLynx interface name on Linux
QB_CONF_DIR="/home/${TORRENT_USER}/.config/qBittorrent"
QB_WEBUI_PORT=8080

echo "=== TorrentRemote server setup ==="

# ── 1. Dependencies ───────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y qbittorrent-nox curl

# ── 2. Service user ───────────────────────────────────────────────────────────
if ! id "$TORRENT_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$TORRENT_USER"
    echo "Created user: $TORRENT_USER"
fi

# ── 3. Download directories ───────────────────────────────────────────────────
mkdir -p "$DOWNLOAD_DIR"/{movies,tv,other,.incomplete}
chown -R "$TORRENT_USER":"$TORRENT_USER" "$DOWNLOAD_DIR"
echo "Download dirs: $DOWNLOAD_DIR/{movies,tv,other}"

# ── 4. qBittorrent config ─────────────────────────────────────────────────────
# Binds to nordlynx so all torrent traffic goes through NordVPN.
# If nordlynx goes down, qBittorrent simply stops transferring — no leaks.
mkdir -p "$QB_CONF_DIR"
cat > "$QB_CONF_DIR/qBittorrent.conf" << EOF
[BitTorrent]
Session\DefaultSavePath=$DOWNLOAD_DIR/other
Session\Interface=$VPN_IFACE
Session\InterfaceName=$VPN_IFACE
Session\TempPath=$DOWNLOAD_DIR/.incomplete
Session\TempPathEnabled=true

[LegalNotice]
Accepted=true

[Preferences]
WebUI\Address=127.0.0.1
WebUI\Port=$QB_WEBUI_PORT
WebUI\Username=admin
WebUI\LocalHostAuth=false
WebUI\CSRFProtection=false
EOF
chown -R "$TORRENT_USER":"$TORRENT_USER" "/home/$TORRENT_USER/.config"
echo "qBittorrent configured (bound to $VPN_IFACE, Web UI on 127.0.0.1:$QB_WEBUI_PORT)"

# ── 5. sudoers — allow Mac to restart qbittorrent-nox via SSH ─────────────────
SUDOERS_FILE="/etc/sudoers.d/torrentremote"
cat > "$SUDOERS_FILE" << EOF
$TORRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart qbittorrent-nox
$TORRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl status qbittorrent-nox
$TORRENT_USER ALL=(ALL) NOPASSWD: /opt/torrentremote/rotate-vpn.sh
EOF
chmod 440 "$SUDOERS_FILE"

# ── 6. systemd service ────────────────────────────────────────────────────────
cat > /etc/systemd/system/qbittorrent-nox.service << EOF
[Unit]
Description=qBittorrent-nox (NordLynx-bound)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$TORRENT_USER
Group=$TORRENT_USER
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do ip link show nordlynx &>/dev/null && exit 0; echo "Waiting for nordlynx (\$i/30)..."; sleep 2; done; echo "ERROR: nordlynx never appeared"; exit 1'
ExecStart=/usr/bin/qbittorrent-nox
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable torrent-netns
systemctl enable qbittorrent-nox
echo "systemd services enabled"

# ── 7. WireGuard tools + namespace scripts ────────────────────────────────────
apt-get install -y wireguard-tools iptables

SCRIPTS_DIR="/opt/torrentremote"
mkdir -p "$SCRIPTS_DIR"
cp scripts/netns-up.sh   "$SCRIPTS_DIR/netns-up.sh"
cp scripts/netns-down.sh "$SCRIPTS_DIR/netns-down.sh"
cp scripts/rotate-vpn.sh "$SCRIPTS_DIR/rotate-vpn.sh"
chmod +x "$SCRIPTS_DIR"/netns-*.sh "$SCRIPTS_DIR/rotate-vpn.sh"

# ── VPN rotation timer (every 6 hours) ───────────────────────────────────────
cat > /etc/systemd/system/nordvpn-rotate.service << EOF
[Unit]
Description=Rotate NordVPN to a fresh P2P server
After=network-online.target

[Service]
Type=oneshot
ExecStart=$SCRIPTS_DIR/rotate-vpn.sh P2P
EOF

cat > /etc/systemd/system/nordvpn-rotate.timer << EOF
[Unit]
Description=Rotate NordVPN server every 6 hours

[Timer]
OnBootSec=6h
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable nordvpn-rotate.timer
echo "VPN rotation timer enabled (every 6 hours)"

# Systemd service: creates the torrent namespace + WireGuard VPN
cat > /etc/systemd/system/torrent-netns.service << EOF
[Unit]
Description=Torrent network namespace (WireGuard VPN)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$SCRIPTS_DIR/netns-up.sh
ExecStop=$SCRIPTS_DIR/netns-down.sh

[Install]
WantedBy=multi-user.target
EOF

echo "WireGuard namespace service created."
echo "Run scripts/get_nordvpn_wg_config.sh <token> to generate /etc/wireguard/nordvpn.conf"

# ── 8. SSH authorized_keys placeholder ───────────────────────────────────────
SSH_DIR="/home/$TORRENT_USER/.ssh"
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"
touch "$SSH_DIR/authorized_keys"
chmod 600 "$SSH_DIR/authorized_keys"
chown -R "$TORRENT_USER":"$TORRENT_USER" "$SSH_DIR"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps (in order):"
echo ""
echo "  1. Copy your Mac SSH public key to this server:"
echo "     ssh-copy-id -i ~/.ssh/id_rsa.pub ${TORRENT_USER}@$(hostname -I | awk '{print $1}')"
echo ""
echo "  2. Log in to NordVPN on this server:"
echo "     sudo -u $TORRENT_USER nordvpn login"
echo ""
echo "  3. Connect (TorrentRemote app can do this, or manually):"
echo "     sudo -u $TORRENT_USER nordvpn connect --group P2P"
echo ""
echo "  4. Start qBittorrent (happens automatically once nordlynx is up):"
echo "     systemctl start qbittorrent-nox"
echo ""
echo "  5. On your Mac, edit config.yaml then:"
echo "     pip install -r requirements.txt"
echo "     streamlit run app.py"
echo ""
echo "  Web UI is accessible ONLY via SSH tunnel — not exposed on LAN."
