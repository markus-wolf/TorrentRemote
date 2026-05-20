# TorrentRemote

Streamlit app running on your Mac that controls a qBittorrent instance on a headless
Ubuntu server. All torrent traffic is routed exclusively through NordVPN (NordLynx).
Downloads land in folders that Emby watches.

```
Mac (browser)                    Ubuntu server
─────────────                    ─────────────────────────────
Streamlit app  ──SSH tunnel──►  qBittorrent  ──nordlynx──►  NordVPN  ──►  internet
                ──SSH──────────►  NordVPN CLI (status / connect)
                                              │
                                        /downloads/{movies,tv,other}
                                              │
                                         Emby server
```

---

## Prerequisites

- Python 3.10+ on your Mac
- SSH key at `~/.ssh/id_rsa` (or update `key_path` in `config.yaml`)
- Ubuntu server set up per [INSTALL.md](INSTALL.md)
  - qBittorrent-nox running, bound to `nordlynx`
  - NordVPN connected
  - Your Mac's SSH public key in `/home/qbittorrent/.ssh/authorized_keys`

---

## Setup

**1. Clone the repo:**

```bash
git clone <repo-url>
cd TorrentRemote
```

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

**3. Edit `config.yaml`:**

```yaml
qbittorrent:
  host: "alexubu"           # server hostname or IP (unused when use_ssh_tunnel: true)
  port: 8080                # qBittorrent Web UI port
  username: "admin"
  password: "adminadmin"    # set during server setup
  use_ssh_tunnel: true
  ssh_tunnel_local_port: 18080

ssh:
  host: "alexubu"           # server hostname or IP
  port: 22
  user: "qbittorrent"       # service user created by setup.sh
  key_path: "~/.ssh/id_rsa"

emby:
  host: "alexubu"
  port: 8096
  api_key: ""               # Emby Dashboard → Advanced → API Keys (blank = disabled)

downloads:
  movies: "/downloads/movies"
  tv:     "/downloads/tv"
  other:  "/downloads/other"
```

**4. Run:**

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501` in your browser. The SSH tunnel to the server
is established automatically on startup — no manual `ssh` command needed.

---

## Usage

### Sidebar

| Element | Description |
|---|---|
| VPN status | Shows NordVPN connection state, server hostname (e.g. `de1036.nordvpn.com`), city/country, and IP. Auto-refreshes every 10 seconds. |
| Connect / Disconnect | Controls NordVPN on the server via SSH. |
| Rotate Server | Switches to a different P2P server in the same country (or one you type). Runs in the background; the status panel updates automatically when reconnected. |
| Transfer | Live global download/upload speed. Auto-refreshes every 5 seconds. Shows a Restart button if qBittorrent is unreachable. |
| Save to | Pick a category (movies / tv / other) — sets the download path on the server. |
| Stop seeding when complete | Toggle — when on, new torrents stop automatically once downloaded (ratio 0). Per-torrent resume is available in the Queue tab. |
| Refresh | Manually force a full page refresh. |

### Add Torrent tab

- **Upload .torrent file** — drag one or more `.torrent` files from Finder into the uploader, then click Add.
- **Paste magnet link** — paste one or more magnet links (one per line), then click Add.

After a successful add, Emby is notified to scan the library immediately (if
`emby.api_key` is configured).

### Queue tab

Auto-refreshes every 5 seconds. Shows all torrents with a circular progress indicator,
name, size, ETA, and per-torrent speeds. Filter by status: All / Downloading / Seeding /
Stopped. Each row has:

| Button | Action |
|---|---|
| ▶ / ⏸ | Resume or pause the torrent |
| ▶ Seed | Resume seeding for a torrent that was auto-stopped on completion |
| 🗑 | Remove from queue (keeps files on disk) |

---

## How the SSH tunnel works

qBittorrent listens on `127.0.0.1:8080` on the server — not exposed on the LAN.
On every page render the app checks whether the tunnel port is reachable. If it isn't
(e.g. after Mac sleep), it kills the stale process and opens a fresh tunnel:

```
ssh -N -L 127.0.0.1:<local_port>:127.0.0.1:8080 qbittorrent@<server>
```

This forwards `localhost:<local_port>` on your Mac to qBittorrent on the server.
No manual `ssh` command or app restart is needed after the Mac wakes from sleep.

---

## VPN kill switch

qBittorrent is bound to the `nordlynx` network interface in its config. If NordVPN
drops, `nordlynx` disappears and qBittorrent immediately loses internet — no traffic
falls back to the real interface. The Streamlit sidebar will show VPN as disconnected
and offer a reconnect button.

---

## VPN server rotation

The **Rotate Server** button in the sidebar triggers `/opt/torrentremote/rotate-vpn.sh`
on the server. The script:

1. Records the current server hostname
2. Disconnects NordVPN
3. Reconnects to a P2P server in the same (or specified) country
4. If the same server is picked, disconnects and reconnects again to force a different one
5. Waits for the `nordlynx` interface to come back up

The script runs entirely in the background — the Streamlit UI returns immediately with a
toast, then auto-updates the VPN status panel when the new connection is established
(~15 seconds).

A systemd timer also rotates the server automatically every 6 hours.
Progress is always logged to `/tmp/rotate-vpn.log` on the server.

---

## Server setup

See [INSTALL.md](INSTALL.md) for the full Ubuntu server setup: qBittorrent-nox,
NordVPN, systemd services, SSH access, VPN rotation, and traffic verification.
