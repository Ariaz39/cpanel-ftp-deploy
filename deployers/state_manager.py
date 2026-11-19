import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class StateManager:
    """Lee y escribe el estado de archivos desplegados (hashes MD5)."""

    def __init__(self):
        cache_dir = os.getenv("STATE_CACHE_DIR")
        if not cache_dir:
            raise RuntimeError(
                "STATE_CACHE_DIR no está definida. "
                "Esta herramienta debe ejecutarse desde GitHub Actions."
            )
        self._state_dir = Path(cache_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, target: str) -> Path:
        return self._state_dir / f"deploy-state-{target}.json"

    def load(self, target: str) -> dict:
        path = self._state_path(target)
        if not path.exists():
            return {"deployed_at": None, "files": {}}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, target: str, files: dict[str, str], **extra) -> dict:
        state = {
            "deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "files": files,
            **extra,
        }
        with open(self._state_path(target), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return state

    @staticmethod
    def parse_remote(raw: bytes | None) -> dict | None:
        """Convierte el JSON descargado del servidor; None si falta o está corrupto."""
        if not raw:
            return None
        try:
            state = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(state, dict) or not isinstance(state.get("files"), dict):
            return None
        return state

    @staticmethod
    def newest(*states: dict | None) -> dict | None:
        """Devuelve el estado más reciente (por deployed_at); None si no hay ninguno."""
        valid = [s for s in states if s and s.get("deployed_at")]
        return max(valid, key=lambda s: s["deployed_at"]) if valid else None

    @staticmethod
    def file_hash(path: str | Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
