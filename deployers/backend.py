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
    ".env",
    ".env.example",
    "phpunit.xml",
    "README.md",
    "node_modules",
}


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
    previous_state = state_manager.load("backend")

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

        _run(["php", "artisan", "config:cache"], project_path, "php artisan config:cache")
        _run(["php", "artisan", "route:cache"], project_path, "php artisan route:cache")
        _run(["php", "artisan", "view:cache"], project_path, "php artisan view:cache")
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
        state_manager.save("backend", new_hashes, composer_lock_hash=current_composer_hash)
        _call_webhook()
        return

    ftp_host = os.environ["FTP_HOST"]
    ftp_user = os.environ["FTP_USER"]
    ftp_password = os.environ["FTP_PASSWORD"]
    remote_base = os.environ.get("FTP_BACKEND_REMOTE_DIR", "/public_html/api/").rstrip("/")

    with FTPClient(ftp_host, ftp_user, ftp_password) as ftp:
        for rel_path, abs_path, _ in tqdm(to_upload, desc="[backend] Subiendo", unit="arch"):
            remote_path = f"{remote_base}/{rel_path}"
            ftp.upload_file(abs_path, remote_path)
            print(f"  {rel_path}  OK")

    state_manager.save("backend", new_hashes)
    print("[backend] Estado actualizado")

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
