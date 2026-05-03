import paramiko
from pathlib import Path
from typing import Tuple, Dict


class VPNManager:
    def __init__(self, host: str, port: int, user: str, key_path: str):
        self.host = host
        self.port = port
        self.user = user
        self.key_path = str(Path(key_path).expanduser())

    def _connect(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            key_filename=self.key_path,
            timeout=10,
            banner_timeout=10,
        )
        return client

    def _run(self, command: str) -> Tuple[str, str, int]:
        client = self._connect()
        try:
            _, stdout, stderr = client.exec_command(command, timeout=20)
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            code = stdout.channel.recv_exit_status()
            return out, err, code
        finally:
            client.close()

    def status(self) -> Dict:
        try:
            out, _, _ = self._run("nordvpn status")
        except Exception as e:
            return {"connected": False, "error": str(e)}

        result: Dict = {"connected": False, "raw": out}
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Status:"):
                result["connected"] = "Connected" in line
            elif line.startswith("Hostname:"):
                result["hostname"] = line.split(":", 1)[1].strip()
            elif line.startswith("IP:"):
                result["ip"] = line.split(":", 1)[1].strip()
            elif line.startswith("Country:"):
                result["country"] = line.split(":", 1)[1].strip()
            elif line.startswith("City:"):
                result["city"] = line.split(":", 1)[1].strip()
            elif line.startswith("Current technology:"):
                result["technology"] = line.split(":", 1)[1].strip()
            elif line.startswith("Transfer:"):
                result["transfer"] = line.split(":", 1)[1].strip()
        return result

    def connect(self, group: str = "P2P") -> Tuple[bool, str]:
        try:
            out, err, code = self._run(f"nordvpn connect --group {group}")
            return code == 0, (out or err)
        except Exception as e:
            return False, str(e)

    def disconnect(self) -> Tuple[bool, str]:
        try:
            out, err, code = self._run("nordvpn disconnect")
            return code == 0, (out or err)
        except Exception as e:
            return False, str(e)

    def restart_qbittorrent(self) -> Tuple[bool, str]:
        try:
            out, err, code = self._run("sudo systemctl restart qbittorrent-nox")
            return code == 0, (out or err or "restarted")
        except Exception as e:
            return False, str(e)
