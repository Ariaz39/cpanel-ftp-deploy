<?php
/**
 * Webhook de post-deploy para Laravel en cPanel.
 *
 * Subir este archivo a la RAÍZ del proyecto Laravel en el servidor
 * (al mismo nivel que artisan) la primera vez, vía FTP manualmente.
 *
 * Puede desactivarse renombrándolo (p.ej. deploy.php.disabled) en el servidor.
 *
 * Uso desde la herramienta de deploy:
 *   POST https://tudominio.com/deploy.php
 *   Header: X-Deploy-Token: <tu_token_secreto>
 */

define('LOG_FILE', __DIR__ . '/storage/logs/deploy.log');

header('Content-Type: application/json');

// ── Bootear Laravel primero para que Dotenv cargue el .env ───────────────────
$autoload = __DIR__ . '/vendor/autoload.php';
$bootstrap = __DIR__ . '/bootstrap/app.php';

if (!file_exists($autoload) || !file_exists($bootstrap)) {
    http_response_code(500);
    echo json_encode(['error' => 'vendor/autoload.php o bootstrap/app.php no encontrado']);
    exit;
}

require $autoload;
$app = require $bootstrap;
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

// ── Validar token (después del bootstrap para que env() lea el .env) ──────────
$secret = env('DEPLOY_BACKEND_SECRET') ?: '';
$token  = $_SERVER['HTTP_X_DEPLOY_TOKEN'] ?? '';
if (!$secret || !hash_equals($secret, $token)) {
    http_response_code(403);
    echo json_encode(['error' => 'Token inválido', 'timestamp' => date('c')]);
    exit;
}

// ── Ejecutar migraciones ──────────────────────────────────────────────────────
try {
    $exitCode = Illuminate\Support\Facades\Artisan::call('migrate', ['--force' => true]);
    $output   = Illuminate\Support\Facades\Artisan::output();

    $migrated = array_values(array_filter(
        explode("\n", trim($output)),
        fn($line) => str_contains($line, 'Migrating:') || str_contains($line, 'Migrated:')
    ));

    $status = ($exitCode === 0) ? 'ok' : 'error';
} catch (Throwable $e) {
    $status   = 'error';
    $migrated = [];
    $output   = $e->getMessage();
}

// ── Registrar en log ──────────────────────────────────────────────────────────
$timestamp = date('c');
$logEntry  = "[{$timestamp}] status={$status} migrated=" . count($migrated) . " output=" . trim($output) . PHP_EOL;
@file_put_contents(LOG_FILE, $logEntry, FILE_APPEND | LOCK_EX);

// ── Responder ─────────────────────────────────────────────────────────────────
http_response_code($status === 'ok' ? 200 : 500);
echo json_encode([
    'status'    => $status,
    'migrated'  => $migrated,
    'output'    => trim($output),
    'timestamp' => $timestamp,
]);
