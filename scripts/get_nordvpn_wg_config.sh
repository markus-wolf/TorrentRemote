#!/usr/bin/env bash
# One-time script: fetches a NordVPN WireGuard config and writes it to
# /etc/wireguard/nordvpn.conf, ready for use in the torrent namespace.
#
# Usage: sudo bash get_nordvpn_wg_config.sh <nordvpn-access-token>
#
# Get your access token at: my.nordaccount.com → NordVPN → Access Tokens

set -euo pipefail

TOKEN="${1:?Usage: $0 <nordvpn-access-token>}"
WG_DIR="/etc/wireguard"
CONF="$WG_DIR/nordvpn.conf"

command -v wg     >/dev/null || { echo "Install wireguard-tools: apt install wireguard-tools"; exit 1; }
command -v curl   >/dev/null || { echo "Install curl: apt install curl"; exit 1; }
command -v python3 >/dev/null || { echo "Install python3"; exit 1; }

mkdir -p "$WG_DIR"
chmod 700 "$WG_DIR"

# ── 1. Generate WireGuard key pair ────────────────────────────────────────────
PRIVATE_KEY=$(wg genkey)
PUBLIC_KEY=$(echo "$PRIVATE_KEY" | wg pubkey)
echo "Generated WireGuard key pair."

# ── 2. Register public key with NordVPN, get server key + assigned IP ─────────
echo "Registering key with NordVPN API..."
REGISTER=$(curl -s --fail \
  -u "token:$TOKEN" \
  -X POST "https://api.nordvpn.com/v1/users/keys" \
  -H "Content-Type: application/json" \
  -d "{\"public_key\": \"$PUBLIC_KEY\"}")

SERVER_PUBLIC_KEY=$(echo "$REGISTER" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['server_public_key'])")
ASSIGNED_IP=$(echo "$REGISTER"       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['ip_address'])")

echo "Assigned IP: $ASSIGNED_IP"

# ── 3. Find the best P2P WireGuard server ─────────────────────────────────────
echo "Finding recommended P2P server..."
SERVERS=$(curl -s --fail \
  "https://api.nordvpn.com/v1/servers/recommendations?filters[servers_technologies][identifier]=wireguard_udp&filters[servers_groups][identifier]=legacy_p2p&limit=1&fields[]=hostname&fields[]=station&fields[]=technologies")

ENDPOINT_IP=$(echo "$SERVERS" | python3 -c "
import sys, json
s = json.load(sys.stdin)[0]
print(s['station'])
")

SERVER_HOSTNAME=$(echo "$SERVERS" | python3 -c "
import sys, json
s = json.load(sys.stdin)[0]
print(s['hostname'])
")

echo "Selected server: $SERVER_HOSTNAME ($ENDPOINT_IP)"

# ── 4. Write WireGuard config ─────────────────────────────────────────────────
cat > "$CONF" << EOF
[Interface]
PrivateKey = $PRIVATE_KEY
Address = $ASSIGNED_IP
DNS = 103.86.96.100, 103.86.99.100

[Peer]
PublicKey = $SERVER_PUBLIC_KEY
Endpoint = $ENDPOINT_IP:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF

chmod 600 "$CONF"
echo ""
echo "Config written to $CONF"
echo "Run setup.sh next to create the torrent namespace and start qBittorrent."
