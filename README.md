# TorrentRemote

Streamlit app running on your Mac that controls a qBittorrent instance on a headless
Ubuntu server. All torrent traffic is routed exclusively through NordVPN (NordLynx).
Downloads land in folders that Emby watches.

```
Mac (browser)                         Ubuntu server
─────────────                         ─────────────────────────────
Streamlit app  ──SSH tunnel────────►  qBittorrent  ──nordlynx──►  NordVPN  ──►  internet
               ──SSH (paramiko)────►  NordVPN CLI (status / connect / rotate)
                                                   │
                                             /downloads/{movies,tv,other}
                                                   │
                                              Emby server
```

The Mac can reach the Ubuntu server from **home** (LAN hostname/IP) or from
**anywhere on the internet** (DDNS hostname + router port forward) — controlled by
which config file you pass at launch.

---

## Prerequisites

- Python 3.10+ on your Mac
- SSH key at `~/.ssh/id_rsa` (or update `key_path` in your config)
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

**3. Create your config file(s):**

Copy the example and fill in your values:

```bash
cp config.example.yaml config.yaml
```

For external (away from home) access, create a second config:

```bash
cp config.external.example.yaml config.external.yaml
```

See [Configuration](#configuration) below for field details.

**4. Run:**

```bash
# at home
streamlit run app.py

# away from home
streamlit run app.py -- --config config.external.yaml
```

The app opens at `http://localhost:8501`. The SSH tunnel to the server is established
automatically — no manual `ssh` command needed. After Mac sleep the tunnel is rebuilt
automatically on the next page interaction.

---

## Configuration

Both `config.yaml` and `config.external.yaml` are gitignored — they hold real credentials
and are never committed. Use the committed `*.example.yaml` files as references.

### Home config (`config.yaml`)

```yaml
qbittorrent:
  host: "alexubu"           # LAN hostname or IP (unused when use_ssh_tunnel: true)
  port: 8080                # qBittorrent Web UI port on the server
  username: "admin"
  password: "adminadmin"    # change via qBittorrent Web UI after first run
  use_ssh_tunnel: true
  ssh_tunnel_local_port: 18080   # local port the tunnel binds on your Mac

ssh:
  host: "alexubu"           # LAN hostname or IP
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

### External config (`config.external.yaml`)

Same structure, with the SSH section pointing at your public DDNS hostname and the
router-forwarded port:

```yaml
ssh:
  host: "yourname.freedynamicdns.org"   # DDNS hostname
  port: 49256                            # external port forwarded to Ubuntu :22
  user: "qbittorrent"
  key_path: "~/.ssh/id_rsa"
```

Everything else can stay the same as the home config.

---

## Usage

### Sidebar

| Element | Description |
|---|---|
| VPN status | Shows NordVPN connection state, server hostname, city/country, and IP. |
| Connect / Disconnect | Controls NordVPN on the server via SSH. |
| Rotate Server | Switches to a different P2P server in the same country (or one you type). Takes ~15–30 s; status updates automatically when done. |
| Transfer | Live global download/upload speed. Auto-refreshes every 5 seconds. Shows a Restart button if qBittorrent is unreachable. |
| Save to | Pick a category (movies / tv / other) — sets the download path on the server. |
| Stop seeding when complete | Toggle — when on, new torrents stop automatically once downloaded (ratio 0). Per-torrent resume is available in the Queue tab. |
| Refresh | Manually force a full page refresh. |

### Add Torrent tab

- **Upload .torrent file** — drag one or more `.torrent` files from Finder, then click Add.
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
On startup the app opens a persistent tunnel:

```
ssh -N -L 127.0.0.1:<local_port>:127.0.0.1:8080 qbittorrent@<server> -p <port>
```

This forwards `localhost:<local_port>` on your Mac to qBittorrent on the server.
No manual `ssh` command is needed. The tunnel process is cached for the lifetime of
the Streamlit server; if it dies the next page render restarts it.

---

## Security

### What is and isn't exposed

| Surface | Exposed? | Notes |
|---|---|---|
| qBittorrent Web UI | **No** | Listens on `127.0.0.1` only; reachable only via SSH tunnel |
| SSH (LAN) | Port 22, LAN only | Key auth only, no password |
| SSH (external) | One non-standard port, public | Key auth only; see below |
| NordVPN / torrent traffic | Via VPN only | Bound to `nordlynx`; stops if VPN drops |

### SSH hardening (Ubuntu server)

Disable password authentication so only key-holders can log in — critical before
exposing any port to the internet:

```bash
sudo nano /etc/ssh/sshd_config
```

Set (or confirm) these lines:

```
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
```

Validate and reload:

```bash
sudo sshd -t          # check for syntax errors
sudo systemctl reload ssh
```

### External port choice

Pick a port in the **49000–65000** range for the router port forward. Bots routinely
scan port 22 and common alternates (222, 2222, 8022); the upper ephemeral range sees
far less automated traffic. The port number alone is not security — key auth is — but
it reduces log noise significantly.

Example: router forwards `external:49256 → ubuntu-lan-ip:22`.

### SSH key on your Mac

Keep your private key protected:

```bash
chmod 600 ~/.ssh/id_rsa
```

If you use the key on multiple machines, consider a passphrase and `ssh-agent` so
the passphrase is entered once per session rather than per connection.

### qBittorrent VPN kill switch

qBittorrent is bound to the `nordlynx` interface in its config. If NordVPN drops,
`nordlynx` disappears and qBittorrent immediately loses internet — torrent traffic
cannot fall back to the real interface. No extra kill-switch configuration is needed.

---

## VPN server rotation

The **Rotate Server** button triggers `/opt/torrentremote/rotate-vpn.sh` on the server.
The script:

1. Records the current server hostname
2. Disconnects NordVPN
3. Reconnects to a P2P server in the same (or specified) country
4. If the same server is picked again, disconnects and reconnects once more
5. Waits for the `nordlynx` interface to come back up

A systemd timer also rotates the server automatically every 6 hours.

---

## Server setup

See [INSTALL.md](INSTALL.md) for the full Ubuntu server setup: qBittorrent-nox,
NordVPN, systemd services, SSH access, external access, VPN rotation, and traffic
verification.
