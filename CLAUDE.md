# CLAUDE.md

Guidance for working in this repo. Keep it short; document only what isn't obvious from the code.

## What this is

A Streamlit app ([app.py](app.py)) that remote-controls a VPN-bound qBittorrent server over an
SSH tunnel. Helpers: [qbit_client.py](qbit_client.py) (qBittorrent Web API), [vpn.py](vpn.py)
(NordVPN over SSH). Server-side provisioning lives in [setup.sh](setup.sh) and `scripts/`.

## Tooling

Managed with **uv** and **Python 3.13** (`pyproject.toml` + `uv.lock`; no `requirements.txt`).

```bash
uv sync                                              # set up the env
uv run streamlit run app.py                          # run (home config)
uv run streamlit run app.py -- --config config.external.yaml   # away-from-home config
```

On startup the app opens an SSH tunnel to the qBittorrent server and calls `st.stop()` if it
fails, so it only renders fully when that server is reachable — a bare local run without the
server will just show a tunnel error.

## Streamlit conventions

This project follows the `developing-with-streamlit` skill's best practices. Notably:

- **Theming gotcha:** appearance is set in [.streamlit/config.toml](.streamlit/config.toml), not
  CSS. Define colors under **both** `[theme.light]` and `[theme.dark]` — never a bare `[theme]`
  block. A bare `[theme]` (even with only `primaryColor`) locks the app to one mode (light by
  default) and overrides the user's OS dark-mode preference. Both-mode definitions preserve
  system light/dark following and the in-app switcher. Verify with `streamlit config show`.
- Prefer native elements over `unsafe_allow_html`; use `width="stretch"` (not the deprecated
  `use_container_width`); Material Symbols icons (`:material/name:`) over emojis on controls.
- The Queue tab's circular SVG progress is intentional custom HTML (no native equivalent).

## Secrets

`config.yaml` / `config.external.yaml` hold real credentials and are gitignored. Never commit
them; `config.example.yaml` documents the shape.
