#!/usr/bin/env bash
# Brings up the 'torrent' network namespace with a WireGuard VPN connection.
# Called by torrent-netns.service on boot. Safe to run multiple times.
set -euo pipefail

NS="torrent"
VETH_HOST="veth-host"
VETH_NS="veth-tor"
HOST_ADDR="10.99.0.1/30"
NS_ADDR="10.99.0.2/30"
NS_GW="10.99.0.1"
WG_CONF="/etc/wireguard/nordvpn.conf"

[ -f "$WG_CONF" ] || { echo "Missing $WG_CONF — run get_nordvpn_wg_config.sh first"; exit 1; }

# ── Namespace ─────────────────────────────────────────────────────────────────
ip netns list | grep -q "^$NS" || ip netns add "$NS"

# ── veth pair (lets WireGuard handshake traffic leave via the host) ────────────
if ! ip link show "$VETH_HOST" &>/dev/null; then
    ip link add "$VETH_HOST" type veth peer name "$VETH_NS"
    ip link set "$VETH_NS" netns "$NS"

    ip addr add "$HOST_ADDR" dev "$VETH_HOST"
    ip link set "$VETH_HOST" up

    ip netns exec "$NS" ip addr add "$NS_ADDR" dev "$VETH_NS"
    ip netns exec "$NS" ip link set "$VETH_NS" up
    ip netns exec "$NS" ip link set lo up
    ip netns exec "$NS" ip route add default via "$NS_GW"
fi

# ── NAT: let the namespace reach the internet for the WireGuard handshake ─────
echo 1 > /proc/sys/net/ipv4/ip_forward
iptables -t nat -C POSTROUTING -s 10.99.0.0/30 -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s 10.99.0.0/30 -j MASQUERADE

# ── WireGuard inside the namespace ────────────────────────────────────────────
# wg-quick sets up wg0, assigns the VPN IP, and replaces the default route
# with the VPN tunnel — all scoped to the 'torrent' namespace only.
if ! ip netns exec "$NS" ip link show wg0 &>/dev/null; then
    ip netns exec "$NS" wg-quick up "$WG_CONF"
fi

echo "Namespace '$NS' is up with WireGuard VPN."
ip netns exec "$NS" ip route   # print routes for confirmation
