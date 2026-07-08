import ftplib
import os
import time
from pathlib import Path, PurePosixPath


class FTPClient:
    """Cliente FTP en modo pasivo con una sola sesión y reintentos automáticos."""

    MAX_RETRIES = 3
    RETRY_DELAY = 5  # segundos entre reintentos

    def __init__(self, host: str, user: str, password: str, timeout: int = 30):
        self._host = host
        self._user = user
        self._password = password
        self._timeout = timeout
        self._ftp: ftplib.FTP | None = None
        self._known_dirs: set[str] = set()

    def connect(self) -> None:
        self._ftp = ftplib.FTP(timeout=self._timeout)
        self._ftp.connect(self._host)
        self._ftp.login(self._user, self._password)
        self._ftp.set_pasv(True)
        self._known_dirs.clear()

    def disconnect(self) -> None:
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                pass
            self._ftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    def _ping(self) -> None:
        """Verifica que la sesión siga activa; reconecta silenciosamente si no."""
        try:
            self._ftp.voidcmd("NOOP")
        except Exception:
            self.disconnect()
            self.connect()

    def _ensure_dir(self, remote_dir: str) -> None:
        if remote_dir in self._known_dirs:
            return
        parts = PurePosixPath(remote_dir).parts
        current = ""
        for part in parts:
            current = str(PurePosixPath(current) / part) if current else part
            if current in self._known_dirs:
                continue
            try:
                self._ftp.cwd(current)
                self._known_dirs.add(current)
            except ftplib.error_perm:
                self._ftp.mkd(current)
                self._ftp.cwd(current)
                self._known_dirs.add(current)
        self._known_dirs.add(remote_dir)

    def upload_file(self, local_path: str | Path, remote_path: str) -> None:
        remote_path = remote_path.replace("\\", "/")
        remote_dir = str(PurePosixPath(remote_path).parent)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._ping()
                self._ensure_dir(remote_dir)
                with open(local_path, "rb") as f:
                    self._ftp.storbinary(f"STOR {remote_path}", f)
                return
            except (ftplib.error_temp, OSError, EOFError) as exc:
                if attempt == self.MAX_RETRIES:
                    raise RuntimeError(
                        f"FTP: falló subir {remote_path} tras {self.MAX_RETRIES} intentos: {exc}"
                    ) from exc
                time.sleep(self.RETRY_DELAY)
                try:
                    self.disconnect()
                    self.connect()
                except Exception:
                    pass
