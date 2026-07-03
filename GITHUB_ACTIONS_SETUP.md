# Configuración de GitHub Actions para deploy automático

Esta guía explica cómo conectar los repositorios de **backend (Laravel)** y
**frontend (Angular)** con esta herramienta de deploy.

---

## Pre-requisitos

- Acceso admin a los repos de tu backend y frontend en GitHub
- Este repo (`cpanel-ftp-deploy`) ya publicado en GitHub (puede ser privado)
- Credenciales FTP del servidor cPanel
- Token secreto para el webhook (genera uno con `openssl rand -hex 32`)

---

## Paso 1 — Configurar Secrets en el repo del backend

1. Ve a `github.com/tu-org/tu-proyecto-backend`
2. Haz clic en **Settings** → **Secrets and variables** → **Actions**
3. Haz clic en **New repository secret** y crea cada uno de estos:

| Nombre del Secret | Descripción | Ejemplo |
|---|---|---|
| `FTP_HOST` | Host FTP del cPanel | `ftp.tudominio.com` |
| `FTP_USER` | Usuario FTP | `deploy@tudominio.com` |
| `FTP_PASSWORD` | Contraseña FTP | `tu_password_ftp` |
| `FTP_BACKEND_REMOTE_DIR` | Ruta destino en el servidor | `/public_html/api/` |
| `DEPLOY_BACKEND_WEBHOOK_URL` | URL del webhook de migraciones | `https://tudominio.com/deploy.php` |
| `DEPLOY_BACKEND_SECRET` | Token secreto para el webhook | `a1b2c3d4e5f6...` (32+ chars) |
| `BACKEND_ENV_PRODUCTION` | Contenido completo del `.env` de producción | `APP_NAME=MiApp\nAPP_ENV=production\n...` |

> **Nota sobre `BACKEND_ENV_PRODUCTION`**: pega el contenido completo del archivo `.env`
> de producción como valor del secret. Las líneas se separan con `\n` literal o
> con saltos de línea reales — GitHub Actions los preserva correctamente.

---

## Paso 2 — Configurar Secrets en el repo del frontend

1. Ve a `github.com/tu-org/tu-proyecto-frontend`
2. **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Nombre del Secret | Descripción | Ejemplo |
|---|---|---|
| `FTP_HOST` | Host FTP del cPanel | `ftp.tudominio.com` |
| `FTP_USER` | Usuario FTP | `deploy@tudominio.com` |
| `FTP_PASSWORD` | Contraseña FTP | `tu_password_ftp` |
| `FTP_FRONTEND_REMOTE_DIR` | Ruta destino en el servidor | `/public_html/` |

---

## Paso 3 — Crear el workflow en el repo del backend

Crea el archivo `.github/workflows/deploy.yml` en tu repo de backend.
Reemplaza `tu-org/tu-proyecto-backend` y `tu-org/cpanel-ftp-deploy` con los valores reales:

```yaml
name: Deploy Backend a cPanel

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      # 1. Descargar el código del backend
      - name: Checkout backend
        uses: actions/checkout@v4
        with:
          path: backend

      # 2. Configurar PHP 8.4 con extensiones necesarias para Laravel
      - name: Setup PHP 8.4
        uses: shivammathur/setup-php@v2
        with:
          php-version: "8.4"
          extensions: mbstring, pdo, pdo_mysql, tokenizer, xml, ctype, json, bcmath

      # 3. Configurar Python para la herramienta de deploy
      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      # 4. Restaurar el estado del deploy anterior (para subir solo lo que cambió)
      - name: Restaurar cache de estado deploy
        uses: actions/cache@v4
        with:
          path: deploy-state
          key: deploy-state-backend-${{ github.ref_name }}
          restore-keys: |
            deploy-state-backend-

      # 5. Descargar la herramienta de deploy
      - name: Checkout herramienta de deploy
        uses: actions/checkout@v4
        with:
          repository: tu-org/cpanel-ftp-deploy
          path: cpanel-ftp-deploy

      # 6. Instalar dependencias Python
      - name: Instalar dependencias Python
        run: pip install -r cpanel-ftp-deploy/requirements.txt

      # 7. Ejecutar el deploy
      - name: Deploy backend
        working-directory: cpanel-ftp-deploy
        env:
          BACKEND_PROJECT_PATH: ${{ github.workspace }}/backend
          STATE_CACHE_DIR: ${{ github.workspace }}/deploy-state
          FTP_HOST: ${{ secrets.FTP_HOST }}
          FTP_USER: ${{ secrets.FTP_USER }}
          FTP_PASSWORD: ${{ secrets.FTP_PASSWORD }}
          FTP_BACKEND_REMOTE_DIR: ${{ secrets.FTP_BACKEND_REMOTE_DIR }}
          DEPLOY_BACKEND_WEBHOOK_URL: ${{ secrets.DEPLOY_BACKEND_WEBHOOK_URL }}
          DEPLOY_BACKEND_SECRET: ${{ secrets.DEPLOY_BACKEND_SECRET }}
          BACKEND_ENV_PRODUCTION: ${{ secrets.BACKEND_ENV_PRODUCTION }}
        run: python deploy.py --target backend

      # 8. Guardar el nuevo estado para el próximo deploy
      - name: Guardar cache de estado deploy
        if: always()
        uses: actions/cache/save@v4
        with:
          path: deploy-state
          key: deploy-state-backend-${{ github.ref_name }}-${{ github.run_id }}
```

---

## Paso 4 — Crear el workflow en el repo del frontend

Crea el archivo `.github/workflows/deploy.yml` en tu repo de frontend.
Reemplaza `tu-org/tu-proyecto-frontend` y `tu-org/cpanel-ftp-deploy` con los valores reales:

```yaml
name: Deploy Frontend a cPanel

on:
  push:
    branches:
      - main

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      # 1. Descargar el código del frontend
      - name: Checkout frontend
        uses: actions/checkout@v4
        with:
          path: frontend

      # 2. Configurar la versión de Node.js del proyecto
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version-file: frontend/.nvmrc
          # Si no tienes .nvmrc, reemplaza la línea anterior por:
          # node-version: "20"

      # 3. Configurar Python para la herramienta de deploy
      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      # 4. Restaurar el estado del deploy anterior
      - name: Restaurar cache de estado deploy
        uses: actions/cache@v4
        with:
          path: deploy-state
          key: deploy-state-frontend-${{ github.ref_name }}
          restore-keys: |
            deploy-state-frontend-

      # 5. Cache de node_modules para acelerar npm install
      - name: Cache node_modules
        uses: actions/cache@v4
        with:
          path: frontend/node_modules
          key: node-modules-${{ hashFiles('frontend/package-lock.json') }}

      # 6. Descargar la herramienta de deploy
      - name: Checkout herramienta de deploy
        uses: actions/checkout@v4
        with:
          repository: tu-org/cpanel-ftp-deploy
          path: cpanel-ftp-deploy

      # 7. Instalar dependencias Python
      - name: Instalar dependencias Python
        run: pip install -r cpanel-ftp-deploy/requirements.txt

      # 8. Ejecutar el deploy
      - name: Deploy frontend
        working-directory: cpanel-ftp-deploy
        env:
          FRONTEND_PROJECT_PATH: ${{ github.workspace }}/frontend
          STATE_CACHE_DIR: ${{ github.workspace }}/deploy-state
          FTP_HOST: ${{ secrets.FTP_HOST }}
          FTP_USER: ${{ secrets.FTP_USER }}
          FTP_PASSWORD: ${{ secrets.FTP_PASSWORD }}
          FTP_FRONTEND_REMOTE_DIR: ${{ secrets.FTP_FRONTEND_REMOTE_DIR }}
        run: python deploy.py --target frontend

      # 9. Guardar el nuevo estado para el próximo deploy
      - name: Guardar cache de estado deploy
        if: always()
        uses: actions/cache/save@v4
        with:
          path: deploy-state
          key: deploy-state-frontend-${{ github.ref_name }}-${{ github.run_id }}
```

---

## Paso 5 — Subir `deploy.php` al servidor (primera vez)

El archivo `deploy.php` de este repo debe estar en la **raíz de Laravel** en el servidor
(al mismo nivel que `artisan`). Se hace **una sola vez manualmente**:

1. Abre tu cliente FTP (FileZilla, WinSCP, o el Administrador de Archivos de cPanel)
2. Conéctate al servidor con las mismas credenciales FTP
3. Navega hasta el directorio del backend (el mismo que `FTP_BACKEND_REMOTE_DIR`)
4. Sube el archivo `deploy.php` de este repositorio
5. Verifica que la URL `https://tudominio.com/deploy.php` responde con `403`
   (lo que significa que el archivo está activo y rechaza tokens inválidos — correcto)

> Para **desactivar** el webhook temporalmente sin borrarlo, renómbralo en el servidor
> a `deploy.php.disabled` usando el Administrador de Archivos de cPanel.

---

## Paso 6 — Verificar que funciona

1. Haz un commit y push a `main` en el repo del backend o frontend
2. Ve a la pestaña **Actions** del repo en GitHub
3. Deberías ver un workflow corriendo. Haz clic para ver los logs en tiempo real
4. Al terminar verás `[deploy] Completado en X | Backend: OK`

### Qué significan los colores

| Color | Significado |
|---|---|
| 🟡 Amarillo (running) | Deploy en curso |
| 🟢 Verde (success) | Deploy exitoso |
| 🔴 Rojo (failure) | Error — haz clic para ver qué falló |

### Cómo relanzar un deploy fallido

En la pestaña Actions, haz clic en el run fallido → botón **Re-run jobs** →
**Re-run failed jobs**. Esto NO crea un nuevo commit, solo vuelve a ejecutar el workflow.

---

## Troubleshooting

### Error: `Connection timed out` o `425 Can't open data connection`
- El servidor cPanel puede bloquear conexiones FTP desde IPs desconocidas
- Solución: en cPanel → **Security** → **IP Blocker** o **FTP Configuration**,
  verifica que el modo pasivo esté habilitado
- Alternativamente, en **cPanel → FTP Connections** revisa si hay conexiones activas

### Error: `403 Forbidden` en el webhook
- Verifica que el valor de `DEPLOY_BACKEND_SECRET` en GitHub Secrets sea exactamente
  el mismo que está en `deploy.php` en el servidor
- Si subiste `deploy.php` después de modificarlo, asegúrate de que la versión en el
  servidor es la más reciente

### El cache de estado se corrompió (sube TODO en cada deploy)
- Ve a Actions → **Caches** (en el sidebar) → elimina el cache `deploy-state-backend-main`
- El próximo deploy hará un deploy completo (normal) y creará un cache limpio

### `BACKEND_ENV_PRODUCTION` no se aplica
- Verifica que el secret esté definido en el repo del **backend** (no en el de deploy)
- Los saltos de línea en secrets de GitHub se preservan — no es necesario usar `\n`

### `vendor/` no se actualiza tras cambiar `composer.lock`
- El deploy compara hashes de TODOS los archivos en `vendor/`
- Si `composer.lock` cambia, composer regenera `vendor/` y todos esos hashes cambian,
  lo que dispara la subida completa del vendor automáticamente
