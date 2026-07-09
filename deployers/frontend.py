import os
import subprocess
from pathlib import Path

from tqdm import tqdm

from .ftp_client import FTPClient
from .state_manager import StateManager


def _run(cmd: list[str], cwd: Path, label: str) -> None:
    print(f"[frontend] {label}...")
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"[frontend] Falló: {' '.join(cmd)}")


def _find_dist(project_path: Path) -> Path:
    """Localiza el directorio browser/ generado por @angular/build:application (Angular 17+).

    La estructura de salida es dist/<proyecto>/browser/.
    Si no existe browser/, usa el primer subdirectorio de dist/ como fallback.
    """
    dist_root = project_path / "dist"
    if not dist_root.exists():
        raise RuntimeError(
            f"[frontend] No se encontró dist/ en {project_path}. "
            "¿Se ejecutó ng build correctamente?"
        )

    browser_dirs = list(dist_root.glob("*/browser"))
    if browser_dirs:
        chosen = browser_dirs[0]
        print(f"[frontend] Build dir: {chosen.relative_to(project_path)}")
        return chosen

    sub_dirs = [d for d in dist_root.iterdir() if d.is_dir()]
    if sub_dirs:
        chosen = sub_dirs[0]
        print(f"[frontend] Build dir (fallback): {chosen.relative_to(project_path)}")
        return chosen

    return dist_root


def _scan_dist(dist_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for file in dist_dir.rglob("*"):
        if file.is_file():
            rel = file.relative_to(dist_dir)
            files[str(rel).replace("\\", "/")] = file
    return files


def deploy_frontend(args) -> None:
    project_path_str = os.environ.get("FRONTEND_PROJECT_PATH")
    if not project_path_str:
        raise RuntimeError("FRONTEND_PROJECT_PATH no está definida")
    project_path = Path(project_path_str).resolve()
    if not project_path.exists():
        raise RuntimeError(f"FRONTEND_PROJECT_PATH no existe: {project_path}")

    print(f"[frontend] Directorio: {project_path}")

    if not args.skip_build:
        _run(["npm", "install"], project_path, "npm install")
        _run(["npm", "run", "build"], project_path, "npm run build")
    else:
        print("[frontend] --skip-build: omitiendo compilación")

    dist_dir = _find_dist(project_path)

    state_manager = StateManager()
    previous_state = state_manager.load("frontend")
    previous_files: dict[str, str] = previous_state.get("files", {})
    print(f"[frontend] Estado anterior: {len(previous_files)} archivos conocidos")

    print("[frontend] Escaneando dist/...")
    all_files = _scan_dist(dist_dir)
    print(f"[frontend] {len(all_files)} archivos encontrados en dist/")

    to_upload: list[tuple[str, Path, str]] = []
    new_hashes: dict[str, str] = {}

    for rel_path, abs_path in all_files.items():
        current_hash = state_manager.file_hash(abs_path)
        new_hashes[rel_path] = current_hash
        if args.force or previous_files.get(rel_path) != current_hash:
            to_upload.append((rel_path, abs_path, current_hash))

    unchanged = len(all_files) - len(to_upload)
    print(f"[frontend] {len(to_upload)} archivos para actualizar, {unchanged} sin cambios")

    if args.dry_run:
        for rel_path, _, _ in to_upload:
            print(f"  [dry-run] {rel_path}")
        print("[frontend] --dry-run: no se subió nada")
        return

    if not to_upload:
        print("[frontend] Nada que subir")
        state_manager.save("frontend", new_hashes)
        return

    ftp_host = os.environ["FTP_HOST"]
    ftp_user = os.environ["FTP_USER"]
    ftp_password = os.environ["FTP_PASSWORD"]
    remote_base = os.environ.get("FTP_FRONTEND_REMOTE_DIR", "/public_html/").rstrip("/")

    with FTPClient(ftp_host, ftp_user, ftp_password) as ftp:
        for rel_path, abs_path, _ in tqdm(to_upload, desc="[frontend] Subiendo", unit="arch"):
            remote_path = f"{remote_base}/{rel_path}"
            ftp.upload_file(abs_path, remote_path)

    state_manager.save("frontend", new_hashes)
    print("[frontend] Estado actualizado")
