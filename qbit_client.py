import requests
from typing import Optional


class QBittorrentClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.base_url = f"http://{host}:{port}/api/v2"
        self.username = username
        self.password = password
        self.session = requests.Session()

    def login(self) -> bool:
        try:
            r = self.session.post(
                f"{self.base_url}/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=5,
            )
            return r.text.strip() in ("Ok.", "Ok")
        except Exception:
            return False

    def _get(self, path: str, **kwargs):
        r = self.session.get(f"{self.base_url}{path}", timeout=8, **kwargs)
        if r.status_code == 403:
            self.login()
            r = self.session.get(f"{self.base_url}{path}", timeout=8, **kwargs)
        return r

    def _post(self, path: str, **kwargs):
        r = self.session.post(f"{self.base_url}{path}", timeout=8, **kwargs)
        if r.status_code == 403:
            self.login()
            r = self.session.post(f"{self.base_url}{path}", timeout=8, **kwargs)
        return r

    def add_torrent_file(
        self,
        file_bytes: bytes,
        filename: str = "file.torrent",
        save_path: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        data = {}
        if save_path:
            data["savepath"] = save_path
        if category:
            data["category"] = category
        try:
            r = self._post(
                "/torrents/add",
                files={"torrents": (filename, file_bytes, "application/x-bittorrent")},
                data=data,
            )
            return r.text.strip() in ("Ok.", "Ok")
        except Exception:
            return False

    def add_magnet(
        self,
        magnet: str,
        save_path: Optional[str] = None,
        category: Optional[str] = None,
    ) -> bool:
        data = {"urls": magnet}
        if save_path:
            data["savepath"] = save_path
        if category:
            data["category"] = category
        try:
            r = self._post("/torrents/add", data=data)
            return r.text.strip() in ("Ok.", "Ok")
        except Exception:
            return False

    def get_torrents(self) -> list:
        try:
            return self._get("/torrents/info").json()
        except Exception:
            return []

    def get_transfer_info(self) -> dict:
        try:
            return self._get("/transfer/info").json()
        except Exception:
            return {}

    def pause_torrent(self, torrent_hash: str) -> bool:
        try:
            r = self._post("/torrents/pause", data={"hashes": torrent_hash})
            return r.status_code == 200
        except Exception:
            return False

    def resume_torrent(self, torrent_hash: str) -> bool:
        try:
            r = self._post("/torrents/resume", data={"hashes": torrent_hash})
            return r.status_code == 200
        except Exception:
            return False

    def delete_torrent(self, torrent_hash: str, delete_files: bool = False) -> bool:
        try:
            r = self._post(
                "/torrents/delete",
                data={"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()},
            )
            return r.status_code == 200
        except Exception:
            return False

    def reachable(self) -> bool:
        try:
            self._get("/app/version")
            return True
        except Exception:
            return False
