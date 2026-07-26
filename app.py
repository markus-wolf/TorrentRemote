import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import yaml

from qbit_client import QBittorrentClient
from vpn import VPNManager

# ── File priority constants ───────────────────────────────────────────────────
PRIO_SKIP    = 0
PRIO_NORMAL  = 1
PRIO_HIGH    = 6
PRIO_MAXIMUM = 7

PRIORITY_LABEL = {PRIO_SKIP: "Skip", PRIO_NORMAL: "Normal", PRIO_HIGH: "High", PRIO_MAXIMUM: "Maximum"}
# Native color-badge markdown directives (replace hand-rolled HTML spans)
PRIORITY_BADGE_MD = {
    PRIO_SKIP:    ":gray-badge[Skip]",
    PRIO_NORMAL:  ":blue-badge[Normal]",
    PRIO_HIGH:    ":orange-badge[High]",
    PRIO_MAXIMUM: ":red-badge[Maximum]",
}


def natural_key(s: str):
    """Sort key that handles embedded integers (S01E02 before S01E10)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def compute_priority_plan(files: list) -> dict:
    """
    Return {file_index: desired_priority} for every non-skipped file.
    Rule: completed → Normal | 1st incomplete → Maximum | 2nd → High | rest → Normal.
    Files with priority==0 (Skip) are left untouched.
    """
    active = [(i, f) for i, f in enumerate(files) if f["priority"] != PRIO_SKIP]
    active.sort(key=lambda x: natural_key(x[1]["name"]))
    plan: dict = {}
    incomplete_seen = 0
    for idx, f in active:
        if f["progress"] >= 1.0:
            plan[idx] = PRIO_NORMAL
        else:
            if incomplete_seen == 0:
                plan[idx] = PRIO_MAXIMUM
            elif incomplete_seen == 1:
                plan[idx] = PRIO_HIGH
            else:
                plan[idx] = PRIO_NORMAL
            incomplete_seen += 1
    return plan


def apply_priority_plan(qbit: QBittorrentClient, hash_: str,
                        files: list, plan: dict) -> list:
    """Apply plan, return list of (name, old_priority, new_priority) changes."""
    buckets: dict = {}
    changes = []
    for idx, desired in plan.items():
        current = files[idx]["priority"]
        if current != desired:
            buckets.setdefault(desired, []).append(idx)
            changes.append((files[idx]["name"], current, desired))
    for priority, ids in buckets.items():
        qbit.set_file_priority(hash_, ids, priority)
    return changes

st.set_page_config(page_title="TorrentRemote", page_icon="🧲", layout="wide")


# ── Config ────────────────────────────────────────────────────────────────────

def _config_path() -> str:
    """Return the config file path from --config argv, defaulting to config.yaml."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default="config.yaml")
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args.config


@st.cache_data(ttl=0)
def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


CONFIG_PROFILES = {
    "config.yaml":          (":material/home:", "Home"),
    "config.external.yaml": (":material/public:", "External"),
}


def _validate_config(path: str) -> tuple[bool, str]:
    """Try to parse path as YAML and check required top-level keys."""
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f)
        if not isinstance(cfg, dict):
            return False, "not a valid YAML mapping"
        for key in ("ssh", "qbittorrent"):
            if key not in cfg:
                return False, f"missing required key: '{key}'"
        return True, ""
    except FileNotFoundError:
        return False, "file not found"
    except yaml.YAMLError as e:
        return False, f"YAML error: {e}"
    except Exception as e:
        return False, str(e)


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
    "All":          None,
    "Incomplete":   "incomplete",   # progress < 100 % (special sentinel)
    "Downloading":  {"downloading", "stalledDL", "checkingDL", "queuedDL", "moving"},
    "Seeding":      {"uploading", "stalledUP", "checkingUP", "queuedUP"},
    "Stopped":      {"pausedDL", "pausedUP", "error", "missingFiles", "unknown"},
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
        if st.button("Rotate server", icon=":material/sync:", width="stretch",
                     help="Pick a different server in the same (or specified) country"):
            ok, msg = vpn.rotate(country=rotate_country)
            if ok:
                st.toast(msg)
            else:
                st.error(msg)
            # fragment will auto-refresh every 10s; force one immediate cycle
            st.rerun(scope="fragment")
        if st.button("Disconnect VPN", width="stretch"):
            with st.spinner("Disconnecting…"):
                ok, msg = vpn.disconnect()
            st.toast(msg)
            st.rerun(scope="fragment")
    else:
        st.error("Disconnected")
        if vs.get("error"):
            st.caption(vs["error"])
        if st.button("Connect VPN (P2P)", type="primary", width="stretch"):
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
        if st.button("Restart qBittorrent", width="stretch"):
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
    filter_keys = list(FILTER_GROUPS.keys())
    status_filter = st.segmented_control(
        "Show",
        filter_keys,
        default=filter_keys[0],
        label_visibility="collapsed",
    )
    if status_filter is None:  # segmented_control allows deselection; fall back to "All"
        status_filter = filter_keys[0]

    states = FILTER_GROUPS[status_filter]
    if states is None:
        torrents = all_torrents
    elif states == "incomplete":
        torrents = [t for t in all_torrents if t.get("progress", 1.0) < 1.0]
    else:
        torrents = [t for t in all_torrents if t.get("state") in states]

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
                if btns[0].button(":material/play_arrow:", key=f"r_{h}", help="Resume"):
                    qbit.resume_torrent(h)
                    st.rerun()
            elif not is_stopped_seeding:
                if btns[0].button(":material/pause:", key=f"p_{h}", help="Pause"):
                    qbit.pause_torrent(h)
                    st.rerun()
            if is_stopped_seeding:
                if btns[1].button("Seed", icon=":material/play_arrow:", key=f"s_{h}", help="Resume seeding"):
                    qbit.set_share_limits(h, ratio_limit=-1, seeding_time_limit=-1)
                    qbit.resume_torrent(h)
                    st.rerun()
            if btns[2].button(":material/delete:", key=f"d_{h}", help="Remove (keep files)"):
                qbit.delete_torrent(h, delete_files=False)
                st.rerun()

    st.caption(f"Updated {time.strftime('%H:%M:%S')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Initialise active config from CLI arg on first load; persists across reruns
    if "config_path" not in st.session_state:
        st.session_state["config_path"] = _config_path()

    cfg = load_config(st.session_state["config_path"])
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

    # Emby SSH tunnel (optional)
    emby_cfg = cfg.get("emby", {})
    emby_url = None
    if emby_cfg.get("use_ssh_tunnel"):
        emby_local = emby_cfg.get("ssh_tunnel_local_port", 18096)
        emby_remote = emby_cfg.get("port", 8096)
        try:
            ensure_tunnel(
                ssh_cfg["host"], ssh_cfg["port"],
                ssh_cfg["user"], ssh_cfg["key_path"],
                emby_local, emby_remote,
            )
            emby_url = f"http://localhost:{emby_local}"
        except Exception as e:
            st.warning(f"Emby tunnel failed: {e}")

    # ── Sidebar ───────────────────────────────────────────────────────────────

    with st.sidebar:
        st.title("🧲 TorrentRemote")

        if emby_url:
            st.link_button("Open Emby", emby_url, icon=":material/tv:", width="stretch")
        elif emby_cfg.get("host") and not emby_cfg.get("use_ssh_tunnel"):
            direct = f"http://{emby_cfg['host']}:{emby_cfg.get('port', 8096)}"
            st.link_button("Open Emby", direct, icon=":material/tv:", width="stretch")

        # VPN status (auto-refreshing fragment)
        render_vpn(vpn)

        st.divider()

        # Transfer speeds (auto-refreshing fragment)
        render_transfer(qbit, vpn)

        st.divider()
        st.caption(f"Updated {time.strftime('%H:%M:%S')}")

        # Config switcher — shown only when both profiles exist on disk
        available = [p for p in CONFIG_PROFILES if Path(p).exists()]
        current_path = st.session_state["config_path"]
        icon, label = CONFIG_PROFILES.get(current_path, (":material/settings:", current_path))
        st.caption(f"Config: {icon} **{label}**")
        if len(available) > 1:
            sw_cols = st.columns(len(available))
            for col, path in zip(sw_cols, available):
                icon, label = CONFIG_PROFILES[path]
                is_active = path == current_path
                if col.button(
                    f"{icon} {label}",
                    key=f"cfg_{path}",
                    type="primary" if is_active else "secondary",
                    width="stretch",
                    disabled=is_active,
                    help=path,
                ):
                    ok, err = _validate_config(path)
                    if ok:
                        st.session_state["config_path"] = path
                        get_tunnel.clear()
                        get_qbit.clear()
                        get_vpn.clear()
                        st.rerun()
                    else:
                        st.warning(f"Cannot switch to {path}: {err}")

        r_col, h_col = st.columns(2)
        r_col.button("Refresh", icon=":material/refresh:", width="stretch")
        if h_col.button("Help", icon=":material/help:", width="stretch"):
            st.session_state["show_help"] = not st.session_state.get("show_help", False)

    # ── Help page ─────────────────────────────────────────────────────────────
    if st.session_state.get("show_help"):
        st.button("← Back", on_click=lambda: st.session_state.update(show_help=False))
        try:
            st.markdown(Path("USAGE.md").read_text())
        except FileNotFoundError:
            st.error("USAGE.md not found.")
        return

    # ── Tabs ──────────────────────────────────────────────────────────────────

    # on_change="rerun" so a tab's .open reflects the current selection, letting us
    # skip the Files tab's synchronous qBittorrent calls when it isn't showing.
    tab_add, tab_queue, tab_files = st.tabs(
        ["Add torrent", "Queue", "Files"], on_change="rerun"
    )

    # Add torrent
    with tab_add:
        # ── Destination & options ──────────────────────────────────────────────
        dl_paths: dict = cfg.get("downloads", {})
        opt_cols = st.columns([3, 1])
        category = opt_cols[0].selectbox(
            "Save to",
            list(dl_paths.keys()),
            format_func=lambda k: f"📁 {k}",
        )
        save_path = dl_paths[category]
        opt_cols[0].caption(save_path)
        stop_seeding = opt_cols[1].toggle(
            "Stop seeding when complete", value=True,
            help="Automatically stop seeding once the download finishes",
        )

        st.divider()

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

    # Files — per-torrent file priority manager.
    # This is the last section of main(); return early when the tab isn't showing so
    # its synchronous qBittorrent calls don't run on every rerun. If more UI is ever
    # added after this block, convert the guard to an `if tab_files.open:` wrapper.
    with tab_files:
        if not tab_files.open:
            return
        all_torrents = qbit.get_torrents()

        # Prefer downloading torrents; fall back to all
        downloading = [t for t in all_torrents
                       if t.get("state") in {"downloading", "stalledDL", "checkingDL",
                                              "queuedDL", "moving", "pausedDL"}]
        candidates = downloading if downloading else all_torrents

        if not candidates:
            st.info("No torrents found.")
        else:
            torrent_opts = sorted(candidates, key=lambda t: t["name"])
            hashes = [t["hash"] for t in torrent_opts]
            labels = {
                t["hash"]: f"{t['name']}  ({t['progress']*100:.1f}%  ·  {STATE_LABELS.get(t['state'], t['state'])})"
                for t in torrent_opts
            }

            # Persist selection across reruns
            if st.session_state.get("_files_hash") not in hashes:
                st.session_state["_files_hash"] = hashes[0]

            selected_hash = st.selectbox(
                "Torrent",
                options=hashes,
                format_func=lambda h: labels[h],
                key="_files_hash",
            )

            sel = next(t for t in torrent_opts if t["hash"] == selected_hash)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("⬇ Download", fmt_speed(sel.get("dlspeed", 0)))
            m2.metric("⬆ Upload",   fmt_speed(sel.get("upspeed", 0)))
            m3.metric("Progress",   f"{sel['progress']*100:.1f}%")
            m4.metric("ETA",        fmt_eta(sel.get("eta", -1)))

            # Action buttons
            btn_col, _, _ = st.columns([2, 2, 6])
            apply_btn = btn_col.button("Apply smart priorities", type="primary",
                                       icon=":material/bolt:", width="stretch",
                                       help="Maximum → 1st incomplete  |  High → 2nd  |  Normal → rest")

            # Fetch files
            files = qbit.get_torrent_files(selected_hash)

            if not files:
                st.warning("No file data returned — torrent may still be loading metadata.")
            else:
                plan = compute_priority_plan(files)

                if apply_btn:
                    changes = apply_priority_plan(qbit, selected_hash, files, plan)
                    if changes:
                        files = qbit.get_torrent_files(selected_hash)
                        plan  = compute_priority_plan(files)
                        st.success(f"Updated {len(changes)} file(s)")
                        for name, old, new in changes:
                            short = name.split("/")[-1]
                            st.markdown(f"- `{short}` &nbsp; "
                                        f"{PRIORITY_BADGE_MD[old]} → {PRIORITY_BADGE_MD[new]}")
                    else:
                        st.info("Priorities already optimal — nothing to change.")

                # ── File table ────────────────────────────────────────────────
                active_files  = [(i, f) for i, f in enumerate(files) if f["priority"] != PRIO_SKIP]
                skipped_files = [(i, f) for i, f in enumerate(files) if f["priority"] == PRIO_SKIP]
                active_files.sort(key=lambda x: natural_key(x[1]["name"]))

                if not active_files:
                    st.warning("All files are marked Skip.")
                else:
                    table_rows = []
                    for idx, f in active_files:
                        desired = plan.get(idx, f["priority"])
                        current = f["priority"]
                        if current != desired:
                            prio = f"{PRIORITY_LABEL[current]} → {PRIORITY_LABEL[desired]}"
                        else:
                            prio = PRIORITY_LABEL[current]
                        table_rows.append({
                            "File": f["name"].split("/")[-1],
                            "Size": fmt_size(f["size"]),
                            "Progress": f["progress"],
                            "Priority": prio,
                        })

                    st.dataframe(
                        pd.DataFrame(table_rows),
                        hide_index=True,
                        column_config={
                            "File": st.column_config.TextColumn("File", width="large"),
                            "Size": st.column_config.TextColumn("Size", width="small"),
                            "Progress": st.column_config.ProgressColumn(
                                "Progress", min_value=0.0, max_value=1.0, format="percent"
                            ),
                            "Priority": st.column_config.TextColumn("Priority", width="small"),
                        },
                    )

                    # Manual per-file priority overrides
                    st.divider()
                    st.caption("Manual priority overrides")
                    prio_options = [PRIO_MAXIMUM, PRIO_HIGH, PRIO_NORMAL, PRIO_SKIP]
                    for idx, f in active_files:
                        name  = f["name"].split("/")[-1]
                        fcols = st.columns([6, 2])
                        fcols[0].caption(name)
                        new_p = fcols[1].selectbox(
                            "Priority",
                            options=prio_options,
                            index=prio_options.index(f["priority"]) if f["priority"] in prio_options else 2,
                            format_func=lambda p: PRIORITY_LABEL[p],
                            key=f"prio_{selected_hash}_{idx}",
                            label_visibility="collapsed",
                        )
                        if new_p != f["priority"]:
                            qbit.set_file_priority(selected_hash, [idx], new_p)
                            st.rerun()

                if skipped_files:
                    with st.expander(f"Skipped files ({len(skipped_files)})"):
                        for _, f in sorted(skipped_files, key=lambda x: natural_key(x[1]["name"])):
                            st.write(f"⬜ {f['name'].split('/')[-1]}")

                incomplete = sum(1 for _, f in active_files if f["progress"] < 1.0)
                complete   = len(active_files) - incomplete
                st.caption(
                    f"{complete} complete  ·  {incomplete} remaining  ·  "
                    f"{len(skipped_files)} skipped  ·  updated {time.strftime('%H:%M:%S')}"
                )


if __name__ == "__main__":
    main()
