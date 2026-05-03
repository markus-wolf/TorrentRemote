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

@st.cache_resource
def get_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, local_port, remote_port):
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

    # Wait up to 5s for the local port to open
    for _ in range(10):
        time.sleep(0.5)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", local_port)) == 0:
                return proc
    proc.kill()
    raise RuntimeError(f"SSH tunnel did not open on port {local_port}")


@st.cache_resource
def get_qbit(host, port, username, password) -> QBittorrentClient:
    client = QBittorrentClient(host, port, username, password)
    client.login()
    return client


@st.cache_resource
def get_vpn(host, port, user, key_path) -> VPNManager:
    return VPNManager(host, port, user, key_path)


# ── Formatters ────────────────────────────────────────────────────────────────

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
    "pausedUP":     "⏸ Done",
    "checkingDL":   "🔍 Checking",
    "checkingUP":   "🔍 Checking",
    "queuedDL":     "⏱ Queued",
    "queuedUP":     "⏱ Queued",
    "moving":       "📦 Moving",
    "error":        "❌ Error",
    "missingFiles": "❌ Missing files",
    "unknown":      "❓ Unknown",
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
            get_tunnel(
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

        # VPN
        st.subheader("VPN")
        try:
            vs = vpn.status()
        except Exception as e:
            vs = {"connected": False, "error": str(e)}

        if vs.get("connected"):
            st.success("Connected")
            loc = " · ".join(filter(None, [vs.get("city"), vs.get("country")]))
            if loc:
                st.caption(loc)
            if vs.get("ip"):
                st.caption(f"IP: {vs['ip']}")
            if vs.get("transfer"):
                st.caption(vs["transfer"])
            if st.button("Disconnect VPN", use_container_width=True):
                with st.spinner("Disconnecting…"):
                    ok, msg = vpn.disconnect()
                st.toast(msg)
                st.rerun()
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
                st.rerun()

        st.divider()

        # Transfer speeds
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

        st.divider()

        # Save-path picker
        st.subheader("Save to")
        dl_paths: dict = cfg.get("downloads", {})
        category = st.selectbox("Category", list(dl_paths.keys()))
        save_path = dl_paths[category]
        st.caption(save_path)

        st.divider()
        st.caption(f"Updated {time.strftime('%H:%M:%S')}")
        st.button("⟳ Refresh", on_click=st.rerun, use_container_width=True)

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
                        ok = qbit.add_magnet(link, save_path=save_path, category=category)
                        label = link[:72] + "…"
                        if ok:
                            st.success(f"Added: {label}")
                            emby_refresh(cfg)
                        else:
                            st.error(f"Failed: {label}")

    # Queue
    with tab_queue:
        torrents = qbit.get_torrents()

        if not torrents:
            st.info("Queue is empty — or qBittorrent is unreachable.")
        else:
            # Summary row
            total_dl = sum(t.get("dlspeed", 0) for t in torrents)
            total_ul = sum(t.get("upspeed", 0) for t in torrents)
            c1, c2, c3 = st.columns(3)
            c1.metric("Torrents", len(torrents))
            c2.metric("Total ↓", fmt_speed(total_dl))
            c3.metric("Total ↑", fmt_speed(total_ul))

            st.divider()

            for t in torrents:
                h = t["hash"]
                state = t.get("state", "unknown")
                progress = t.get("progress", 0.0)
                is_paused = "paused" in state.lower()

                name_col, size_col, eta_col, state_col, act_col = st.columns(
                    [5, 1, 1, 2, 2]
                )
                name_col.markdown(f"**{t['name']}**")
                size_col.text(fmt_size(t.get("size", 0)))
                eta_col.text(fmt_eta(t.get("eta", -1)))
                state_col.text(STATE_LABELS.get(state, state))

                with act_col:
                    btn_pause, btn_del = st.columns(2)
                    if is_paused:
                        if btn_pause.button("▶", key=f"r_{h}", help="Resume"):
                            qbit.resume_torrent(h)
                            st.rerun()
                    else:
                        if btn_pause.button("⏸", key=f"p_{h}", help="Pause"):
                            qbit.pause_torrent(h)
                            st.rerun()
                    if btn_del.button("🗑", key=f"d_{h}", help="Remove (keep files)"):
                        qbit.delete_torrent(h, delete_files=False)
                        st.rerun()

                dl = fmt_speed(t.get("dlspeed", 0))
                ul = fmt_speed(t.get("upspeed", 0))
                st.progress(progress, text=f"{progress * 100:.1f}%  ↓{dl}  ↑{ul}")
                st.divider()


if __name__ == "__main__":
    main()
