# Ubuntu Server Setup

All commands run on the Ubuntu server as a user with `sudo` access, unless noted.

---

## 1. Install qBittorrent-nox

```bash
sudo apt update
sudo apt install -y qbittorrent-nox curl
```

`qbittorrent-nox` is the headless (no GUI) version — it exposes only the Web UI.

---

## 2. Create the service user

```bash
sudo useradd --system --create-home --shell /bin/bash qbittorrent
```

- `--system` marks it as a service account (no login by default, lower UID range)
- `--create-home` creates `/home/qbittorrent` where config will live
- Verify: `id qbittorrent`

---

## 3. Create download directories

```bash
sudo mkdir -p /downloads/{movies,tv,other,.incomplete}
sudo chown -R qbittorrent:qbittorrent /downloads
```

Emby will point at `/downloads/movies` and `/downloads/tv`. `.incomplete` holds partial
downloads so Emby never sees half-finished files.

---

## 4. Write the qBittorrent config

This is the critical step — it binds qBittorrent to the `nordlynx` interface so all
torrent traffic is VPN-only.

```bash
sudo mkdir -p /home/qbittorrent/.config/qBittorrent
sudo tee /home/qbittorrent/.config/qBittorrent/qBittorrent.conf > /dev/null << 'EOF'
[BitTorrent]
Session\DefaultSavePath=/downloads/other
Session\Interface=nordlynx
Session\InterfaceName=nordlynx
Session\TempPath=/downloads/.incomplete
Session\TempPathEnabled=true

[LegalNotice]
Accepted=true

[Preferences]
WebUI\Address=127.0.0.1
WebUI\Port=8080
WebUI\Username=admin
WebUI\Password_PBKDF2="@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAneJe/wFNe5nXaipEl5IrpIk=)"
WebUI\LocalHostAuth=false
WebUI\CSRFProtection=false
EOF

sudo chown -R qbittorrent:qbittorrent /home/qbittorrent/.config
```

The password hash above corresponds to `adminadmin`. Change it via the Web UI after
first login.

**Key settings:**

| Setting | Effect |
|---|---|
| `Session\Interface=nordlynx` | qBittorrent sends/receives only on the NordLynx interface. If NordVPN drops, `nordlynx` disappears and torrent traffic silently stops — no leak. |
| `WebUI\Address=127.0.0.1` | Web UI listens on localhost only, never reachable from the LAN directly. The Mac reaches it via SSH tunnel. |
| `WebUI\Password_PBKDF2` | Must be present — newer qBittorrent rejects all connections if no password hash is set. |
| `WebUI\LocalHostAuth=false` | Skips auth for API clients (curl, Streamlit). |

---

## 5. Allow the qbittorrent user to restart its own service

The Streamlit app restarts qBittorrent and runs the VPN rotation script via SSH.
These sudoers entries allow both without a password prompt:

```bash
sudo tee /etc/sudoers.d/torrentremote > /dev/null << 'EOF'
qbittorrent ALL=(ALL) NOPASSWD: /bin/systemctl restart qbittorrent-nox
qbittorrent ALL=(ALL) NOPASSWD: /bin/systemctl status qbittorrent-nox
qbittorrent ALL=(ALL) NOPASSWD: /opt/torrentremote/rotate-vpn.sh
EOF

sudo chmod 440 /etc/sudoers.d/torrentremote
```

Verify the syntax is valid:

```bash
sudo visudo -c -f /etc/sudoers.d/torrentremote
```

---

## 6. Create the systemd service

```bash
sudo tee /etc/systemd/system/qbittorrent-nox.service > /dev/null << 'EOF'
[Unit]
Description=qBittorrent-nox (NordLynx-bound)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=qbittorrent
Group=qbittorrent
ExecStartPre=/bin/bash -c 'for i in $(seq 1 30); do ip link show nordlynx &>/dev/null && exit 0; echo "Waiting for nordlynx ($i/30)..."; sleep 2; done; echo "ERROR: nordlynx never appeared"; exit 1'
ExecStart=/usr/bin/qbittorrent-nox
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable qbittorrent-nox
```

The `ExecStartPre` line waits up to 60 seconds for the `nordlynx` interface to appear
before launching qBittorrent. This prevents it starting on a raw connection if the server
reboots before NordVPN reconnects.

> **Do not start the service yet** — NordVPN must be set up first.

---

## 7. Install and configure NordVPN

```bash
curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh | sh
```

Add the qbittorrent user to the `nordvpn` group so it can run `nordvpn` commands:

```bash
sudo usermod -aG nordvpn qbittorrent
```

Apply all settings before connecting for the first time:

```bash
nordvpn set technology nordlynx   # WireGuard-based, creates the 'nordlynx' interface
nordvpn set firewall off           # prevents NordVPN's iptables rules from killing SSH
nordvpn set routing off            # prevents NordVPN from replacing the default route
nordvpn set killswitch off         # redundant with the above, but explicit
nordvpn set autoconnect on P2P     # reconnect automatically on reboot
```

**Why `firewall off` and `routing off`:** NordVPN's firewall installs iptables rules that
intercept all traffic on connect, which freezes existing SSH sessions. With both settings
off, NordVPN only creates the `nordlynx` interface — nothing else on the host is touched.
qBittorrent is protected because it is bound to `nordlynx` in its config: if the VPN
drops, `nordlynx` disappears and qBittorrent simply cannot send traffic.

### Headless login

On a headless server you cannot open a browser, so use the callback URL method:

1. Run on the server — it prints a URL:
```bash
nordvpn login
```

2. Open that URL on your **Mac**. After logging in, the browser address bar shows:
```
https://nordaccount.com/product/nordvpn/login/success?exchange_token=<token>&...
```

3. Back on the server, extract the `exchange_token` value and run:
```bash
nordvpn login --callback "nordvpn://login?exchange_token=<token>"
```

Note: `%3D%3D` in the URL is URL-encoding for `==` — decode it before pasting.

4. Confirm login:
```bash
nordvpn account
```

> The exchange token is a credential — revoke it at `my.nordaccount.com → Access Tokens`
> after confirming login worked.

### Connect

```bash
nordvpn connect --group P2P
```

Confirm the interface appeared and the default route is unchanged:

```bash
ip link show nordlynx        # should show UP
ip route                     # default should still point to your LAN gateway, not nordlynx
curl --interface nordlynx ifconfig.me   # should return a NordVPN IP
```

---

## 8. Set up SSH access for the Mac

The Streamlit app connects using your Mac's SSH key — for the tunnel and for VPN/service
commands. Prepare the `authorized_keys` file for the `qbittorrent` user:

```bash
sudo mkdir -p /home/qbittorrent/.ssh
sudo chmod 700 /home/qbittorrent/.ssh
sudo touch /home/qbittorrent/.ssh/authorized_keys
sudo chmod 600 /home/qbittorrent/.ssh/authorized_keys
sudo chown -R qbittorrent:qbittorrent /home/qbittorrent/.ssh
```

`ssh-copy-id` won't work here because the `qbittorrent` system account has no password.
Instead, print your public key on your **Mac**:

```bash
cat ~/.ssh/id_rsa.pub
```

Copy the output, then on the **Ubuntu server** (as your normal sudo user), paste it in:

```bash
sudo bash -c 'echo "ssh-rsa AAAA...your full key here..." >> /home/qbittorrent/.ssh/authorized_keys'
```

Verify it landed correctly:

```bash
sudo cat /home/qbittorrent/.ssh/authorized_keys
```

Test the connection from your **Mac**:

```bash
ssh -p 22 qbittorrent@<server-lan-ip> 'echo ok'
```

---

## 9. Harden SSH (required before external access)

Disable password authentication so only key-holders can log in:

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
sudo sshd -t          # check for syntax errors — must return no output
sudo systemctl reload ssh
```

> **Do this before opening any port to the internet.** With password auth disabled,
> brute-force attacks against SSH are ineffective regardless of which port is used.

---

## 10. External access (away from home)

To reach the server from outside your home network you need two things:

### Router port forward

In your router admin panel, add a port forwarding rule:

| Field | Value |
|---|---|
| External port | A port in the 49000–65000 range (e.g. `49256`) |
| Internal IP | Your Ubuntu server's LAN IP |
| Internal port | `22` |
| Protocol | TCP |

Avoid port 22 and common alternates (222, 2222, 8022) externally — bots scan these
constantly. A high non-standard port dramatically reduces log noise. The real security
is the SSH key, but there is no reason to invite automated scanners.

### DDNS

If your ISP assigns a dynamic public IP, set up DDNS so you always have a stable
hostname to connect to. Most home routers have a built-in DDNS client that updates
automatically when the IP changes — configure it in the router admin panel and note
the hostname it gives you (e.g. `yourname.freedynamicdns.org`).

### Mac config

Create `config.external.yaml` from the template:

```bash
cp config.external.example.yaml config.external.yaml
```

Edit the `ssh` section:

```yaml
ssh:
  host: "yourname.freedynamicdns.org"   # DDNS hostname
  port: 49256                            # external port from the router rule
  user: "qbittorrent"
  key_path: "~/.ssh/id_rsa"
```

Then run the app with the external config:

```bash
uv run streamlit run app.py -- --config config.external.yaml
```

### Test from outside

The easiest test before leaving home is to use your phone's mobile data (not Wi-Fi)
and try:

```bash
ssh -p 49256 qbittorrent@yourname.freedynamicdns.org 'echo ok'
```

---

## 11. First run

Start qBittorrent (NordVPN must already be connected):

```bash
sudo systemctl start qbittorrent-nox
systemctl status qbittorrent-nox
```

Verify qBittorrent is listening on localhost only:

```bash
sudo ss -tlnp | grep 8080
# should show 127.0.0.1:8080
```

Test the API through the SSH tunnel from your **Mac**:

```bash
# Open the tunnel in one terminal
ssh -L 8080:127.0.0.1:8080 qbittorrent@<server-ip> -N

# In another terminal, test the API
curl http://localhost:8080/api/v2/auth/login \
  -d "username=admin&password=adminadmin"
# should return: Ok.
```

---

## 12. Verify VPN binding

Add a torrent via the Streamlit app, then on the server:

**Active connections use the VPN IP as source:**
```bash
sudo ss -tupn | grep qbittorrent
# local addresses should show 10.5.0.x (nordlynx), not 192.168.1.x (LAN)
```

**Torrent traffic flows through nordlynx:**
```bash
sudo tcpdump -i nordlynx -n --line-buffered | head -20
# should show peer connections
```

**No torrent traffic leaks on the real interface:**
```bash
sudo tcpdump -i enp2s0 -n 'not port 22' --line-buffered | head -20
# should show nothing except DNS — no BitTorrent peer traffic
```

---

## 13. VPN server rotation

The Streamlit sidebar has a **Rotate Server** button that switches to a different NordVPN
P2P server in the same country (or a country you specify) without interrupting the SSH
session. The rotation script runs on the server; the UI auto-updates within ~20 seconds.

### Install the rotation script

```bash
sudo mkdir -p /opt/torrentremote
sudo cp scripts/rotate-vpn.sh /opt/torrentremote/rotate-vpn.sh
sudo chmod +x /opt/torrentremote/rotate-vpn.sh
```

Test it manually first:

```bash
sudo /opt/torrentremote/rotate-vpn.sh
# or to rotate to a specific country:
sudo /opt/torrentremote/rotate-vpn.sh Netherlands
```

### Automatic rotation timer (every 6 hours)

```bash
sudo tee /etc/systemd/system/nordvpn-rotate.service > /dev/null << 'EOF'
[Unit]
Description=Rotate NordVPN to a fresh P2P server
After=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/torrentremote/rotate-vpn.sh
EOF

sudo tee /etc/systemd/system/nordvpn-rotate.timer > /dev/null << 'EOF'
[Unit]
Description=Rotate NordVPN server every 6 hours

[Timer]
OnBootSec=6h
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nordvpn-rotate.timer
```

Verify the timer is scheduled:

```bash
systemctl list-timers nordvpn-rotate.timer
```

---

## Boot sequence

On reboot the correct order is automatic if autoconnect is enabled:

1. Ubuntu boots, network comes up
2. NordVPN daemon reconnects (`autoconnect on` handles this)
3. `nordlynx` interface appears
4. systemd starts `qbittorrent-nox` (the `ExecStartPre` wait loop handles timing)
