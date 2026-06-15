<#
.SYNOPSIS
  Bring up the full V-CORE web stack, including the SFT tool-router.

.DESCRIPTION
  The SFT tool-router (docs/sft/data/vcore-toolrouter.gguf, q5_k_m) is served by a *host*
  llama-server.exe on :8080 — a Windows CUDA build (Intermediate/llama-build, build 9559 with
  the qwen35 loader fixes), so it cannot live inside a Linux compose container. `docker compose up`
  configures the backend (LLM_PROVIDER=routing_split in web/.env) to call host.docker.internal:8080,
  but it does NOT start that host process. Without it the backend comes up but /llm/status = failed.

  This script closes that gap: it launches the host llama-server (idempotently — skipped if :8080 is
  already healthy), waits for it, then runs `docker compose up -d`. Run it after a reboot instead of
  a bare `docker compose up`.

.PARAMETER RouterOnly
  Start only the host llama-server; skip `docker compose up -d`.

.EXAMPLE
  ./start-router.ps1
.EXAMPLE
  ./start-router.ps1 -RouterOnly
#>
[CmdletBinding()]
param([switch]$RouterOnly)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$server = Join-Path $root "Intermediate/llama-build/bin/Release/llama-server.exe"
$model  = Join-Path $root "docs/sft/data/vcore-toolrouter.gguf"
$log    = Join-Path $root "docs/sft/data/server_log.txt"

function Test-Router {
    try { (Invoke-RestMethod -Uri "http://localhost:8080/health" -TimeoutSec 3).status -eq "ok" }
    catch { $false }
}

if (Test-Router) {
    Write-Host "[router] :8080 already healthy - leaving the running llama-server in place."
} else {
    foreach ($p in @($server, $model)) {
        if (-not (Test-Path $p)) { throw "Missing required file: $p" }
    }
    Write-Host "[router] launching host llama-server on :8080 ..."
    # --no-mtp is a convert-only flag and is NOT valid for serving (build 9559) — do not add it.
    $args = @("-m", $model, "--host", "0.0.0.0", "--port", "8080",
              "-ngl", "99", "-c", "8192", "--jinja", "--reasoning", "off", "--reasoning-budget", "0")
    Start-Process -FilePath $server -ArgumentList $args -WindowStyle Hidden `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"

    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Router)) {
        if ((Get-Date) -gt $deadline) { throw "llama-server did not become healthy within 60s — see $log" }
        Start-Sleep -Seconds 2
    }
    Write-Host "[router] :8080 healthy."
}

if ($RouterOnly) {
    Write-Host "[done] router up (RouterOnly). Skipping docker compose."
    return
}

Write-Host "[compose] docker compose up -d ..."
Push-Location (Join-Path $root "web")
try { docker compose up -d } finally { Pop-Location }
Write-Host "[done] stack up. Check: curl http://localhost:8000/llm/status (expect status=ready)."
