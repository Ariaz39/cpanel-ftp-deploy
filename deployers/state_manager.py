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

    def save(self, target: str, files: dict[str, str]) -> None:
        state = {
            "deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "files": files,
        }
        with open(self._state_path(target), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    @staticmethod
    def file_hash(path: str | Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
