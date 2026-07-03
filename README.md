# cpanel-ftp-deploy

Herramienta Python para desplegar **Laravel (backend)** y **Angular (frontend)**
a un servidor cPanel con solo acceso FTP.

Sube únicamente los archivos que cambiaron comparando hashes MD5 con el deploy anterior.
El estado del deploy vive en **GitHub Actions Cache** — esto garantiza que el cache
siempre refleja exactamente lo que hay en el servidor y evita desincronizaciones.

> Esta herramienta **solo se ejecuta desde GitHub Actions**. No está diseñada para
> uso local: el estado persistido en Actions Cache es la fuente de verdad.

## Cómo funciona

```
push a main en backend o frontend
  → GitHub Actions hace checkout del repo
  → Compila (composer install / ng build)
  → Restaura deploy-state.json desde Actions Cache
  → Compara hashes MD5 de cada archivo vs. estado anterior
  → Sube SOLO los archivos que cambiaron vía FTP
  → Guarda el nuevo deploy-state.json en Actions Cache
  → (Backend) Llama al webhook para ejecutar migraciones
```

## Estructura

```
deployCpanelAutomate/
├── deploy.py                  # CLI principal (ejecutado por GitHub Actions)
├── deployers/
│   ├── ftp_client.py          # Cliente FTP pasivo con reintentos
│   ├── state_manager.py       # Gestión de deploy-state.json (solo Actions Cache)
│   ├── backend.py             # Build y deploy Laravel
│   └── frontend.py            # Build y deploy Angular
├── deploy.php                 # Webhook para migraciones (subir al servidor 1a vez)
├── .deploy.env.example        # Referencia de variables (se configuran como Secrets)
├── requirements.txt
└── GITHUB_ACTIONS_SETUP.md    # Guía completa de configuración en GitHub
```

## Configuración

Ver **[GITHUB_ACTIONS_SETUP.md](GITHUB_ACTIONS_SETUP.md)** para la guía completa:

1. Configurar Secrets en el repo del backend
2. Configurar Secrets en el repo del frontend
3. Crear `.github/workflows/deploy.yml` en cada repo (workflows listos para copiar)
4. Subir `deploy.php` al servidor una sola vez vía FTP
5. Verificar que funciona desde la pestaña Actions de GitHub

## Opciones del CLI

| Opción | Descripción |
|---|---|
| `--target backend/frontend/all` | Qué desplegar (requerido) |
| `--dry-run` | Simula sin subir nada, muestra qué se subiría |
| `--force` | Ignora el estado anterior y sube todos los archivos |
| `--skip-build` | Omite composer/npm/ng build |
