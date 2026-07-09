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

define('LOG_FILE', dirname(__DIR__) . '/storage/logs/deploy.log');

header('Content-Type: application/json');

$root      = dirname(__DIR__);
$autoload  = $root . '/vendor/autoload.php';
$bootstrap = $root . '/bootstrap/app.php';

// ── Validar token leyendo el .env directamente (env() falla con config cache) ─
function _readEnvValue(string $file, string $key): string {
    if (!file_exists($file)) return '';
    foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if ($line === '' || $line[0] === '#') continue;
        [$k, $v] = array_pad(explode('=', $line, 2), 2, '');
        if (trim($k) === $key) return trim($v, "\"' \t");
    }
    return '';
}

$secret = _readEnvValue($root . '/.env', 'DEPLOY_BACKEND_SECRET');
$token  = $_SERVER['HTTP_X_DEPLOY_TOKEN'] ?? '';
if (!$secret || !hash_equals($secret, $token)) {
    http_response_code(403);
    echo json_encode([
        'error'          => 'Token inválido',
        'secret_len'     => strlen($secret),
        'token_len'      => strlen($token),
        'secret_preview' => substr($secret, 0, 6) . '...',
        'timestamp'      => date('c'),
    ]);
    exit;
}

// ── Bootear Laravel ───────────────────────────────────────────────────────────
if (!file_exists($autoload) || !file_exists($bootstrap)) {
    http_response_code(500);
    echo json_encode(['error' => 'vendor/autoload.php o bootstrap/app.php no encontrado']);
    exit;
}

require $autoload;
$app    = require $bootstrap;
$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

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
