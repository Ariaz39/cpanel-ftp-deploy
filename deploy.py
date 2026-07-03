#!/usr/bin/env python3
"""
Herramienta de deploy: Laravel (backend) y Angular (frontend) → cPanel vía FTP.

Uso:
    python deploy.py --target backend
    python deploy.py --target frontend
    python deploy.py --target all
    python deploy.py --target all --dry-run
    python deploy.py --target backend --force
    python deploy.py --target frontend --skip-build
"""
import argparse
import os
import sys
import time


def _separator():
    print("─" * 42)


def _check_environment() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        print(
            "[deploy] ERROR: Esta herramienta solo puede ejecutarse desde GitHub Actions.\n"
            "         El estado del deploy vive en Actions Cache — ejecutarla localmente\n"
            "         desincronizaría el estado con lo que hay en el servidor cPanel.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    _check_environment()

    parser = argparse.ArgumentParser(
        description="Deploy de Laravel y/o Angular a cPanel vía FTP"
    )
    parser.add_argument(
        "--target",
        choices=["backend", "frontend", "all"],
        required=True,
        help="Qué desplegar: backend, frontend, o ambos (all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula el deploy sin subir nada",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora el estado anterior y sube todos los archivos",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Omite la compilación (composer install / npm install / ng build)",
    )
    args = parser.parse_args()

    targets = ["backend", "frontend"] if args.target == "all" else [args.target]
    label = "backend + frontend" if args.target == "all" else args.target

    print(f"[deploy] Target: {label}")
    if args.dry_run:
        print("[deploy] Modo: DRY-RUN — no se subirá nada")
    if args.force:
        print("[deploy] Modo: FORCE — se subirán todos los archivos")
    _separator()

    start = time.monotonic()
    results: dict[str, str] = {}

    from deployers.backend import deploy_backend
    from deployers.frontend import deploy_frontend

    for target in targets:
        t_start = time.monotonic()
        try:
            if target == "backend":
                deploy_backend(args)
            else:
                deploy_frontend(args)
            elapsed = time.monotonic() - t_start
            results[target] = f"OK ({elapsed:.1f}s)"
        except Exception as exc:
            elapsed = time.monotonic() - t_start
            results[target] = f"ERROR ({elapsed:.1f}s)"
            print(f"[{target}] ERROR: {exc}", file=sys.stderr)
            print(f"\n[deploy] Abortado por error en {target}.", file=sys.stderr)
            _separator()
            total = time.monotonic() - start
            _print_summary(results, total)
            sys.exit(1)

    _separator()
    total = time.monotonic() - start
    _print_summary(results, total)


def _print_summary(results: dict[str, str], total: float) -> None:
    parts = " | ".join(f"{k.capitalize()}: {v}" for k, v in results.items())
    mins = int(total // 60)
    secs = total % 60
    if mins:
        elapsed_str = f"{mins}m {secs:.0f}s"
    else:
        elapsed_str = f"{secs:.1f}s"
    print(f"[deploy] Completado en {elapsed_str} | {parts}")


if __name__ == "__main__":
    main()
