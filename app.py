import socket
import subprocess
import time
from pathlib import Path

import requests
import streamlit as st
import yaml

from qbit_client import QBittorrentClient
from vpn import VPNManager

st.set_page_config(page_title="TorrentRemote", page_icon="🧲", layout="wide")


# ── Config ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=0)
def load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


# ── Singletons (survive Streamlit reruns) ─────────────────────────────────────

def _open_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port):
    key = str(Path(ssh_key_path).expanduser())
    cmd = [
        "ssh", "-N",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-i", key,
        "-p", str(ssh_port),
        "-L", f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
        f"{ssh_user}@{ssh_host}",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(10):
        time.sleep(0.5)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", local_port)) == 0:
                return proc
    proc.kill()
    raise RuntimeError(f"SSH tunnel did not open on port {local_port}")


@st.cache_resource
def get_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port):
    return _open_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port)


def ensure_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port):
    """Check tunnel is alive; silently rebuild it if not (e.g. after Mac sleep)."""
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", local_port)) == 0:
            return  # alive

    # Port unreachable — kill stale process and recreate
    try:
        old = get_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port)
        if old and old.poll() is None:
            old.kill()
    except Exception:
        pass

    get_tunnel.clear()
    get_qbit.clear()

    get_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port)


@st.cache_resource
def get_qbit(host, port, username, password) -> QBittorrentClient:
    client = QBittorrentClient(host, port, username, password)
    client.login()
    return client


@st.cache_resource
def get_vpn(host, port, user, key_path) -> VPNManager:
    return VPNManager(host, port, user, key_path)


# ── Formatters & helpers ──────────────────────────────────────────────────────

def circle_progress(pct: float, state: str) -> str:
    size, r = 36, 13
    cx = cy = size / 2
    circ = 2 * 3.14159265 * r
    dash = pct * circ
    if state in ("downloading", "stalledDL", "checkingDL", "queuedDL", "moving"):
        color = "#3b82f6"
    elif state in ("uploading", "stalledUP", "checkingUP", "queuedUP"):
        color = "#22c55e"
    elif state == "pausedUP":
        color = "#10b981"
    elif state in ("error", "missingFiles"):
        color = "#ef4444"
    else:
        color = "#6b7280"
    label = f"{int(pct * 100)}%"
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#374151" stroke-width="3"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="3"'
        f' stroke-dasharray="{dash:.2f} {circ:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy + 3.5}" text-anchor="middle" font-size="7.5"'
        f' fill="{color}" font-family="monospace" font-weight="bold">{label}</text>'
        f'</svg>'
    )


def fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def fmt_speed(bps: int) -> str:
    return fmt_size(bps) + "/s"


def fmt_eta(seconds: int) -> str:
    if seconds < 0 or seconds > 8_640_000:
        return "∞"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


STATE_LABELS = {
    "downloading":  "⬇ Downloading",
    "uploading":    "⬆ Seeding",
    "stalledDL":    "⏳ Stalled",
    "stalledUP":    "⏳ Seeding (stalled)",
    "pausedDL":     "⏸ Paused",
    "pausedUP":     "⏸ Stopped",
    "checkingDL":   "🔍 Checking",
    "checkingUP":   "🔍 Checking",
    "queuedDL":     "⏱ Queued",
    "queuedUP":     "⏱ Queued",
    "moving":       "📦 Moving",
    "error":        "❌ Error",
    "missingFiles": "❌ Missing files",
    "unknown":      "❓ Unknown",
}

FILTER_GROUPS = {
    "All":         None,
    "Downloading": {"downloading", "stalledDL", "checkingDL", "queuedDL", "moving"},
    "Seeding":     {"uploading", "stalledUP", "checkingUP", "queuedUP"},
    "Stopped":     {"pausedDL", "pausedUP", "error", "missingFiles", "unknown"},
}


def emby_refresh(cfg: dict):
    emby = cfg.get("emby", {})
    api_key = emby.get("api_key", "")
    if not api_key:
        return
    url = f"http://{emby['host']}:{emby['port']}/library/refresh"
    try:
        requests.post(url, headers={"X-Emby-Token": api_key}, timeout=5)
    except Exception:
        pass


# ── VPN status fragment (auto-refreshes every 10 seconds) ────────────────────

@st.fragment(run_every=10)
def render_vpn(vpn: VPNManager):
    st.subheader("VPN")
    try:
        vs = vpn.status()
    except Exception as e:
        vs = {"connected": False, "error": str(e)}

    if vs.get("connected"):
        st.success("Connected")
        if vs.get("hostname"):
            st.caption(vs["hostname"])
        loc = " · ".join(filter(None, [vs.get("city"), vs.get("country")]))
        if loc:
            st.caption(loc)
        if vs.get("ip"):
            st.caption(f"IP: {vs['ip']}")
        if vs.get("transfer"):
            st.caption(vs["transfer"])
        rotate_country = st.text_input(
            "Rotate to country",
            value=vs.get("country", ""),
            placeholder="e.g. Netherlands (blank = current)",
            label_visibility="collapsed",
        )
        if st.button("🔄 Rotate Server", use_container_width=True,
                     help="Pick a different server in the same (or specified) country"):
            ok, msg = vpn.rotate(country=rotate_country)
            if ok:
                st.toast(msg)
            else:
                st.error(msg)
            # fragment will auto-refresh every 10s; force one immediate cycle
            st.rerun(scope="fragment")
        if st.button("Disconnect VPN", use_container_width=True):
            with st.spinner("Disconnecting…"):
                ok, msg = vpn.disconnect()
            st.toast(msg)
            st.rerun(scope="fragment")
    else:
        st.error("Disconnected")
        if vs.get("error"):
            st.caption(vs["error"])
        if st.button("Connect VPN (P2P)", type="primary", use_container_width=True):
            with st.spinner("Connecting…"):
                ok, msg = vpn.connect("P2P")
            if ok:
                st.toast(msg)
            else:
                st.error(msg)
            st.rerun(scope="fragment")


# ── Transfer fragment (auto-refreshes every 5 seconds) ───────────────────────

@st.fragment(run_every=5)
def render_transfer(qbit: QBittorrentClient, vpn: VPNManager):
    st.subheader("Transfer")
    info = qbit.get_transfer_info()
    if info:
        c1, c2 = st.columns(2)
        c1.metric("↓", fmt_speed(info.get("dl_info_speed", 0)))
        c2.metric("↑", fmt_speed(info.get("up_info_speed", 0)))
    else:
        st.caption("qBittorrent unreachable")
        if st.button("Restart qBittorrent", use_container_width=True):
            with st.spinner("Restarting…"):
                ok, msg = vpn.restart_qbittorrent()
            st.toast(msg)
            time.sleep(3)
            st.rerun()


# ── Queue fragment (auto-refreshes every 5 seconds) ──────────────────────────

@st.fragment(run_every=5)
def render_queue(qbit: QBittorrentClient):
    all_torrents = qbit.get_torrents()

    if not all_torrents:
        st.info("Queue is empty — or qBittorrent is unreachable.")
        return

    # Summary row
    total_dl = sum(t.get("dlspeed", 0) for t in all_torrents)
    total_ul = sum(t.get("upspeed", 0) for t in all_torrents)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(all_torrents))
    c2.metric("Downloading", sum(1 for t in all_torrents if t.get("state") in FILTER_GROUPS["Downloading"]))
    c3.metric("Total ↓", fmt_speed(total_dl))
    c4.metric("Total ↑", fmt_speed(total_ul))

    # Filter
    status_filter = st.radio(
        "Show",
        list(FILTER_GROUPS.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )

    states = FILTER_GROUPS[status_filter]
    torrents = [t for t in all_torrents if states is None or t.get("state") in states]

    if not torrents:
        st.caption(f"No {status_filter.lower()} torrents.")
        return

    st.divider()
    for t in torrents:
        h = t["hash"]
        state = t.get("state", "unknown")
        progress = t.get("progress", 0.0)
        is_paused = "paused" in state.lower()
        is_stopped_seeding = state == "pausedUP"
        dl = fmt_speed(t.get("dlspeed", 0))
        ul = fmt_speed(t.get("upspeed", 0))

        col_prog, col_name, col_meta, col_act = st.columns([1, 6, 3, 3])

        col_prog.markdown(circle_progress(progress, state), unsafe_allow_html=True)

        col_name.markdown(
            f"**{t['name']}**  \n"
            f"<small style='color:gray'>{fmt_size(t.get('size', 0))} &nbsp;·&nbsp; "
            f"{STATE_LABELS.get(state, state)}</small>",
            unsafe_allow_html=True,
        )

        col_meta.markdown(
            f"<small style='color:gray'>ETA&nbsp;</small>**{fmt_eta(t.get('eta', -1))}**&nbsp;&nbsp;"
            f"<small style='color:gray'>↓</small>{dl}&nbsp;"
            f"<small style='color:gray'>↑</small>{ul}",
            unsafe_allow_html=True,
        )

        with col_act:
            btns = st.columns(3)
            if is_paused and not is_stopped_seeding:
                if btns[0].button("▶", key=f"r_{h}", help="Resume"):
                    qbit.resume_torrent(h)
                    st.rerun()
            elif not is_stopped_seeding:
                if btns[0].button("⏸", key=f"p_{h}", help="Pause"):
                    qbit.pause_torrent(h)
                    st.rerun()
            if is_stopped_seeding:
                if btns[1].button("▶ Seed", key=f"s_{h}", help="Resume seeding"):
                    qbit.set_share_limits(h, ratio_limit=-1, seeding_time_limit=-1)
                    qbit.resume_torrent(h)
                    st.rerun()
            if btns[2].button("🗑", key=f"d_{h}", help="Remove (keep files)"):
                qbit.delete_torrent(h, delete_files=False)
                st.rerun()

    st.caption(f"Updated {time.strftime('%H:%M:%S')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()
    qbit_cfg = cfg["qbittorrent"]
    ssh_cfg = cfg["ssh"]

    # SSH tunnel
    qbit_host = "127.0.0.1"
    qbit_port = qbit_cfg["port"]

    if qbit_cfg.get("use_ssh_tunnel"):
        local_port = qbit_cfg.get("ssh_tunnel_local_port", 18080)
        try:
            ensure_tunnel(
                ssh_cfg["host"], ssh_cfg["port"],
                ssh_cfg["user"], ssh_cfg["key_path"],
                local_port, qbit_cfg["port"],
            )
            qbit_port = local_port
        except Exception as e:
            st.error(f"SSH tunnel failed: {e}")
            st.stop()
    else:
        qbit_host = qbit_cfg["host"]

    qbit = get_qbit(qbit_host, qbit_port, qbit_cfg["username"], qbit_cfg["password"])
    vpn = get_vpn(ssh_cfg["host"], ssh_cfg["port"], ssh_cfg["user"], ssh_cfg["key_path"])

    # ── Sidebar ───────────────────────────────────────────────────────────────

    with st.sidebar:
        st.title("🧲 TorrentRemote")

        # VPN status (auto-refreshing fragment)
        render_vpn(vpn)

        st.divider()

        # Transfer speeds (auto-refreshing fragment)
        render_transfer(qbit, vpn)

        st.divider()

        # Save-path picker
        st.subheader("Save to")
        dl_paths: dict = cfg.get("downloads", {})
        category = st.selectbox("Category", list(dl_paths.keys()))
        save_path = dl_paths[category]
        st.caption(save_path)

        st.divider()

        # Seeding behaviour
        st.subheader("Options")
        stop_seeding = st.toggle("Stop seeding when complete", value=True)

        st.divider()
        st.caption(f"Updated {time.strftime('%H:%M:%S')}")
        st.button("⟳ Refresh", use_container_width=True)

    # ── Tabs ──────────────────────────────────────────────────────────────────

    tab_add, tab_queue = st.tabs(["Add Torrent", "Queue"])

    # Add Torrent
    with tab_add:
        col_file, col_mag = st.columns(2, gap="large")

        with col_file:
            st.subheader("Upload .torrent file")
            uploaded = st.file_uploader(
                "Choose file(s)",
                type=["torrent"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            if uploaded and st.button("Add file(s)", type="primary", key="btn_files"):
                for f in uploaded:
                    qbit.login()
                    ok = qbit.add_torrent_file(
                        f.read(), filename=f.name,
                        save_path=save_path, category=category,
                        stop_seeding=stop_seeding,
                    )
                    if ok:
                        st.success(f"Added: {f.name}")
                        emby_refresh(cfg)
                    else:
                        st.error(f"Failed: {f.name}")

        with col_mag:
            st.subheader("Paste magnet link(s)")
            raw = st.text_area(
                "One per line",
                placeholder="magnet:?xt=urn:btih:…",
                height=160,
                label_visibility="collapsed",
            )
            if st.button("Add magnet(s)", type="primary", key="btn_magnets"):
                links = [l.strip() for l in raw.splitlines() if l.strip().startswith("magnet:")]
                if not links:
                    st.warning("No valid magnet links found.")
                else:
                    for link in links:
                        qbit.login()
                        ok = qbit.add_magnet(
                            link, save_path=save_path, category=category,
                            stop_seeding=stop_seeding,
                        )
                        label = link[:72] + "…"
                        if ok:
                            st.success(f"Added: {label}")
                            emby_refresh(cfg)
                        else:
                            st.error(f"Failed: {label}")

    # Queue
    with tab_queue:
        render_queue(qbit)


if __name__ == "__main__":
    main()
