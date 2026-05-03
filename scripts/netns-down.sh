#!/usr/bin/env bash
# Tears down the 'torrent' namespace cleanly.
# Called by torrent-netns.service on stop.
set -euo pipefail

NS="torrent"
WG_CONF="/etc/wireguard/nordvpn.conf"

ip netns exec "$NS" wg-quick down "$WG_CONF" 2>/dev/null || true
ip netns del "$NS" 2>/dev/null || true
ip link del veth-host 2>/dev/null || true
iptables -t nat -D POSTROUTING -s 10.99.0.0/30 -j MASQUERADE 2>/dev/null || true

echo "Namespace '$NS' torn down."
