# TorrentRemote — User Interface Guide

This guide assumes the server is running, NordVPN is connected, and the Streamlit app
has started successfully. For setup instructions see [INSTALL.md](INSTALL.md).

---

## Sidebar

### VPN

Shows the current NordVPN state. Auto-refreshes every 10 seconds.

**When connected:**

| Field | Example |
|---|---|
| Status | ✅ Connected |
| Server hostname | `de1036.nordvpn.com` |
| Location | Berlin · Germany |
| IP | 185.93.xx.xx |

**Rotate Server** — picks a different P2P server in the same country (or a country you
type in the field above the button). The script runs in the background on the server;
the VPN panel updates automatically when the new connection is established (~15–30 s).
Progress is logged to `/tmp/rotate-vpn.log` on the server.

**Disconnect / Connect VPN (P2P)** — manually disconnect or reconnect NordVPN.
While disconnected, qBittorrent stops transferring (it is bound to the VPN interface).

---

### Transfer

Live global download / upload speed polled from qBittorrent. Auto-refreshes every 5 s.

If qBittorrent is unreachable a **Restart qBittorrent** button appears — this restarts
the systemd service on the server via SSH.

---

### Refresh

Forces a full page reload. Normally not needed — the VPN, Transfer, and Queue sections
all auto-refresh on their own timers.

---

## Add Torrent tab

### Save to

Dropdown at the top of the tab. Selects the destination folder on the server:

| Option | Server path |
|---|---|
| movies | `/downloads/movies` |
| tv | `/downloads/tv` |
| other | `/downloads/other` |

The resolved path is shown as a caption under the dropdown.

> **TV shows:** place episodes under `tv` and name them `Show Name S01E01.mkv` so Emby
> recognises them as series rather than movies.

### Stop seeding when complete

Toggle (default: on). When enabled, each torrent you add is given a ratio limit of 0 —
it stops automatically the moment the download finishes. Individual torrents can be
resumed for seeding later from the Queue tab.

### Upload .torrent file

Drag one or more `.torrent` files from Finder into the upload area, then click
**Add file(s)**. Multiple files are added in one click.

### Paste magnet link(s)

Paste one or more magnet links into the text area, one per line, then click
**Add magnet(s)**. Non-magnet lines are silently ignored.

After a successful add the Emby library scan is triggered automatically
(if `emby.api_key` is configured in your config file).

---

## Queue tab

Auto-refreshes every 5 seconds.

### Summary row

| Metric | Meaning |
|---|---|
| Total | Number of torrents in the client |
| Downloading | Active downloads right now |
| Total ↓ | Combined download speed |
| Total ↑ | Combined upload speed |

### Filter bar

| Filter | Shows |
|---|---|
| All | Every torrent |
| Incomplete | Any torrent with progress < 100 % (regardless of state) |
| Downloading | Actively downloading, stalled, queued, checking, moving |
| Seeding | Uploading, seeding-stalled, seeding-queued |
| Stopped | Paused, stopped-after-complete, error, missing files |

### Torrent rows

Each row shows:

```
● 67%   Show.Name.S02E04   4.3 GB · ⬇ Downloading   ETA 2h 14m  ↓1.2 MB/s  ↑0 B/s   ▶  🗑
```

| Element | Meaning |
|---|---|
| Circular indicator | Progress % with colour: blue = downloading, green = seeding, teal = stopped-complete, red = error |
| Name + state label | Torrent name and current qBittorrent state |
| Size | Total torrent size |
| ETA | Estimated time to completion (∞ = unknown or not downloading) |
| ↓ / ↑ | Per-torrent speeds |

### Row buttons

| Button | Action |
|---|---|
| ▶ | Resume a paused download |
| ⏸ | Pause an active download |
| ▶ Seed | Resume seeding for a torrent stopped after completing (auto-stop was on) |
| 🗑 | Remove from queue — **files are kept on disk** |

---

## Files tab

Per-torrent file priority manager. Useful for multi-episode season packs where you want
to watch episodes in order as they download rather than waiting for the whole pack.

The selector is pre-populated with **downloading** torrents. If none are downloading,
all torrents are listed.

### Metrics row

Shows per-torrent download speed, upload speed, overall progress, and ETA.

### ⚡ Apply Smart Priorities

Automatically assigns priorities so the episodes you can watch soonest finish first:

| Position | Priority | Colour |
|---|---|---|
| Completed files | Normal | 🔵 |
| 1st incomplete file | Maximum | 🔴 |
| 2nd incomplete file | High | 🟠 |
| Remaining incomplete | Normal | 🔵 |

Files you have manually set to **Skip** are never touched by this button.

After applying, the table refreshes and shows what changed
(`Normal → Maximum`, etc.).

### File table

| Column | Meaning |
|---|---|
| File | Filename (without folder prefix) |
| Size | File size |
| Progress | Mini progress bar + percentage, or ✅ when complete |
| Priority | Current priority badge; shows `current → planned` if Smart Priorities haven't been applied yet |

### Manual priority overrides

A dropdown below the table lets you set any individual file's priority directly:

| Value | Effect |
|---|---|
| Maximum 🔴 | Highest bandwidth allocation |
| High 🟠 | Second priority |
| Normal 🔵 | Standard allocation |
| Skip ⬜ | Excluded from download entirely |

Changes take effect immediately — no Apply button needed.

### Skipped files

Files marked Skip are collapsed into an expander at the bottom so they don't clutter
the main table.

---

## Emby link

If `emby.host` is set in your config, an **Open Emby** button appears at the top of the
sidebar. Clicking it opens the Emby web interface in a new browser tab.
