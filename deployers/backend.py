import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import requests
from tqdm import tqdm

from .ftp_client import FTPClient
from .state_manager import StateManager

EXCLUDED = {
    ".git",
    ".github",
    ".claude",
    "tests",
    ".env.example",
    "phpunit.xml",
    "README.md",
    "node_modules",
    "bootstrap/cache",
}

# Estado del deploy guardado en el servidor (no caduca como el Actions Cache).
# Vive dentro del docroot porque el usuario FTP no tiene acceso fuera de él;
# el .htaccess raíz reescribe todo a /public/, así que no se sirve por web.
REMOTE_STATE_PATH = "storage/.deploy-state-backend.json"
CHECKPOINT_EVERY = 100  # archivos subidos entre guardados parciales del estado


def _run(cmd: list[str], cwd: Path, label: str) -> None:
    print(f"[backend] {label}...")
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"[backend] Falló: {' '.join(cmd)}")


def _write_env(project_path: Path) -> None:
    env_value = os.environ.get("BACKEND_ENV_PRODUCTION", "")
    if not env_value:
        raise RuntimeError("BACKEND_ENV_PRODUCTION no está definida")

    env_path_candidate = Path(env_value)
    if env_path_candidate.exists():
        content = env_path_candidate.read_text(encoding="utf-8")
    else:
        content = env_value.replace("\\n", "\n")

    (project_path / ".env").write_text(content, encoding="utf-8")
    print("[backend] .env de producción escrito OK")


def _scan_files(project_path: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for file in project_path.rglob("*"):
        if not file.is_file():
            continue
        rel = file.relative_to(project_path)
        parts = rel.parts
        if any(p in EXCLUDED for p in parts):
            continue
        files[str(rel).replace("\\", "/")] = file
    return files


def deploy_backend(args) -> None:
    project_path_str = os.environ.get("BACKEND_PROJECT_PATH")
    if not project_path_str:
        raise RuntimeError("BACKEND_PROJECT_PATH no está definida")
    project_path = Path(project_path_str).resolve()
    if not project_path.exists():
        raise RuntimeError(f"BACKEND_PROJECT_PATH no existe: {project_path}")

    print(f"[backend] Directorio: {project_path}")

    _write_env(project_path)

    state_manager = StateManager()
    cache_state = state_manager.load("backend")

    ftp_host = os.environ.get("FTP_HOST")
    ftp_user = os.environ.get("FTP_USER")
    ftp_password = os.environ.get("FTP_PASSWORD")
    remote_base = os.environ.get("FTP_BACKEND_REMOTE_DIR", "/public_html/api/").rstrip("/")
    remote_state_path = f"{remote_base}/{REMOTE_STATE_PATH}"

    remote_state = None
    if ftp_host and ftp_user and ftp_password:
        with FTPClient(ftp_host, ftp_user, ftp_password) as ftp:
            remote_state = StateManager.parse_remote(ftp.download_bytes(remote_state_path))

    previous_state = StateManager.newest(remote_state, cache_state)
    if previous_state is None:
        previous_state = {"deployed_at": None, "files": {}}
        print("[backend] Sin estado previo — se subirá todo el proyecto")
    elif previous_state is remote_state:
        print("[backend] Estado cargado desde el servidor")
    else:
        print("[backend] Estado cargado desde Actions Cache (el servidor no tiene estado)")

    if not args.skip_build:
        composer_lock = project_path / "composer.lock"
        current_composer_hash = state_manager.file_hash(composer_lock) if composer_lock.exists() else None
        previous_composer_hash = previous_state.get("composer_lock_hash")

        if current_composer_hash and current_composer_hash == previous_composer_hash:
            print("[backend] composer.lock sin cambios — omitiendo composer install")
        else:
            _run(
                ["composer", "install", "--no-dev", "--optimize-autoloader"],
                project_path,
                "composer install --no-dev",
            )

        print("[backend] Caches de Laravel generados en el servidor vía webhook")
    else:
        print("[backend] --skip-build: omitiendo compilación")
        current_composer_hash = None

    previous_files: dict[str, str] = previous_state.get("files", {})
    print(f"[backend] Estado anterior: {len(previous_files)} archivos conocidos")

    print("[backend] Escaneando build actual...")
    all_files = _scan_files(project_path)
    print(f"[backend] {len(all_files)} archivos encontrados")

    to_upload: list[tuple[str, Path, str]] = []
    new_hashes: dict[str, str] = {}

    for rel_path, abs_path in all_files.items():
        current_hash = state_manager.file_hash(abs_path)
        new_hashes[rel_path] = current_hash
        if args.force or previous_files.get(rel_path) != current_hash:
            to_upload.append((rel_path, abs_path, current_hash))

    unchanged = len(all_files) - len(to_upload)
    print(f"[backend] {len(to_upload)} archivos para actualizar, {unchanged} sin cambios")

    if args.dry_run:
        for rel_path, _, _ in to_upload:
            print(f"  [dry-run] {rel_path}")
        print("[backend] --dry-run: no se subió nada")
        return

    if not to_upload:
        print("[backend] Nada que subir")
        state = state_manager.save("backend", new_hashes, composer_lock_hash=current_composer_hash)
        if remote_state is None and ftp_host and ftp_user and ftp_password:
            # El servidor aún no tiene estado (p. ej. primer run tras caducar el cache)
            with FTPClient(ftp_host, ftp_user, ftp_password) as ftp:
                ftp.upload_bytes(json.dumps(state, indent=2).encode("utf-8"), remote_state_path)
            print("[backend] Estado sincronizado en el servidor")
        _call_webhook()
        return

    if not (ftp_host and ftp_user and ftp_password):
        raise RuntimeError("FTP_HOST, FTP_USER y FTP_PASSWORD son obligatorias para subir archivos")

    # Hashes confirmados en el servidor: arranca con lo anterior y se actualiza por cada
    # archivo subido, así un corte a mitad de camino no obliga a re-subir todo.
    confirmed: dict[str, str] = dict(previous_files)

    def checkpoint(ftp: FTPClient) -> None:
        state = state_manager.save("backend", confirmed, composer_lock_hash=current_composer_hash)
        ftp.upload_bytes(json.dumps(state, indent=2).encode("utf-8"), remote_state_path)

    with FTPClient(ftp_host, ftp_user, ftp_password) as ftp:
        for i, (rel_path, abs_path, file_hash) in enumerate(
            tqdm(to_upload, desc="[backend] Subiendo", unit="arch"), start=1
        ):
            ftp.upload_file(abs_path, f"{remote_base}/{rel_path}")
            confirmed[rel_path] = file_hash
            print(f"  {rel_path}  OK")
            if i % CHECKPOINT_EVERY == 0:
                checkpoint(ftp)

        # Estado final completo (descarta archivos que ya no existen en el build)
        confirmed = new_hashes
        checkpoint(ftp)

    print("[backend] Estado actualizado (local y servidor)")

    _call_webhook()


def _call_webhook() -> None:
    url = os.environ.get("DEPLOY_BACKEND_WEBHOOK_URL")
    token = os.environ.get("DEPLOY_BACKEND_SECRET")
    if not url:
        print("[backend] DEPLOY_BACKEND_WEBHOOK_URL no definida — omitiendo webhook")
        return

    print("[backend] Llamando webhook de migraciones...")
    try:
        resp = requests.post(url, headers={"X-Deploy-Token": token or ""}, timeout=30)
        print(f"[backend] OK - {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"[backend] ADVERTENCIA: webhook falló: {exc}", file=sys.stderr)
