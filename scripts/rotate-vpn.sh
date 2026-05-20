#!/usr/bin/env bash
# Rotates to a different NordVPN server in the same (or specified) country.
# Relies on NordVPN's load balancer to pick a different server on reconnect.
#
# Usage: rotate-vpn.sh [country]
#   country — optional, e.g. "Netherlands" or "United_States"
#             defaults to the currently connected country

set -euo pipefail

nordvpn_disconnect() {
    nordvpn disconnect 2>/dev/null | grep -iv "rate\|scale\|quality\|type" || true
}

nordvpn_connect() {
    nordvpn connect --group P2P "$1" 2>/dev/null | grep -iv "rate\|scale\|quality\|type" || true
}

# Strip ANSI colour codes from nordvpn output
STATUS=$(nordvpn status 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g')

CURRENT_HOST=$(echo "$STATUS" | grep -i "Hostname" | sed 's/.*: //' | tr -d '[:space:]' || true)
CURRENT_PREFIX=$(echo "$CURRENT_HOST" | cut -d. -f1)

TARGET_COUNTRY="${1:-}"
if [ -z "$TARGET_COUNTRY" ]; then
    TARGET_COUNTRY=$(echo "$STATUS" | grep -i "Country" | sed 's/.*: //' | tr -d '\r' || true)
fi

# NordVPN CLI expects underscores for multi-word country names
COUNTRY_ARG=$(echo "$TARGET_COUNTRY" | tr ' ' '_')

echo "[rotate-vpn] Current : $CURRENT_HOST"
echo "[rotate-vpn] Rotating: $TARGET_COUNTRY"

# ── Disconnect ────────────────────────────────────────────────────────────────
nordvpn_disconnect

for i in $(seq 1 10); do
    ip link show nordlynx &>/dev/null || break
    sleep 1
done

# ── Reconnect ─────────────────────────────────────────────────────────────────
nordvpn_connect "$COUNTRY_ARG"

NEW_HOST=$(nordvpn status 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -i "Hostname" | sed 's/.*: //' | tr -d '[:space:]' || true)

if [ "$NEW_HOST" = "$CURRENT_HOST" ]; then
    echo "[rotate-vpn] Same server selected, forcing second rotation..."
    nordvpn_disconnect
    sleep 3
    nordvpn_connect "$COUNTRY_ARG"
fi

# ── Wait for nordlynx ─────────────────────────────────────────────────────────
for i in $(seq 1 30); do
    if ip link show nordlynx &>/dev/null; then
        FINAL=$(nordvpn status 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -i "Hostname" | sed 's/.*: //' | tr -d '[:space:]' || true)
        echo "[rotate-vpn] Connected: $FINAL"
        exit 0
    fi
    sleep 2
done

echo "[rotate-vpn] ERROR: nordlynx did not come back up"
exit 1
