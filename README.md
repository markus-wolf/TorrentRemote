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
| VPN status | Shows NordVPN connection state, server location and IP. Connect/Disconnect buttons control NordVPN on the server via SSH. |
| Transfer | Live global download/upload speed from qBittorrent. If unreachable, shows a Restart button. |
| Save to | Pick a category (movies / tv / other) — sets the download path on the server. |
| Refresh | Manually refresh all data. |

### Add Torrent tab

- **Upload .torrent file** — drag one or more `.torrent` files from Finder into the uploader, then click Add.
- **Paste magnet link** — paste one or more magnet links (one per line), then click Add.

After a successful add, Emby is notified to scan the library immediately (if
`emby.api_key` is configured).

### Queue tab

Shows all torrents with name, size, ETA, state, and a progress bar with per-torrent
speeds. Each row has pause/resume and delete (keeps files) buttons.

---

## How the SSH tunnel works

qBittorrent listens on `127.0.0.1:8080` on the server — not exposed on the LAN.
On startup the app runs:

```
ssh -N -L 127.0.0.1:<local_port>:127.0.0.1:8080 qbittorrent@<server>
```

This forwards `localhost:<local_port>` on your Mac to qBittorrent on the server.
The tunnel process lives for the duration of the Streamlit session.

---

## VPN kill switch

qBittorrent is bound to the `nordlynx` network interface in its config. If NordVPN
drops, `nordlynx` disappears and qBittorrent immediately loses internet — no traffic
falls back to the real interface. The Streamlit sidebar will show VPN as disconnected
and offer a reconnect button.

---

## Server setup

See [INSTALL.md](INSTALL.md) for the full Ubuntu server setup: qBittorrent-nox,
NordVPN, systemd services, SSH access, and VPN verification.
