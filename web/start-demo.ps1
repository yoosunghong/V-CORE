# Start the V-CORE web demo with the adapter-toggle LLM (single model in VRAM).
#
# The chatbot-backend (in Docker) talks to a host llama.cpp server on :8080 that serves
# ONE base model + the routing LoRA, toggled per request. That server is a host process,
# NOT managed by docker compose — this script starts it (if not already up), waits for it
# to be healthy, then brings up the stack. Run from anywhere:
#
#   powershell -ExecutionPolicy Bypass -File web/start-demo.ps1
#
# Pass -Build to force a backend image rebuild (docker compose up --build -d).
# Pass -Force to stop any running llama-server and relaunch it with the correct base + routing
# LoRA — use this when a wrong-but-healthy model may be serving :8080 (the "already healthy"
# check below would otherwise leave it in place).

param([switch]$Build, [switch]$Force)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

function Resolve-VcorePath([string]$Value, [string]$Default) {
    $path = if ($Value) { [Environment]::ExpandEnvironmentVariables($Value) } else { $Default }
    if ([IO.Path]::IsPathRooted($path)) { return $path }
    return Join-Path $repo $path
}

$llamaServer = Resolve-VcorePath $env:VCORE_LLAMA_SERVER `
    (Join-Path $repo "Intermediate/llama-build/bin/Release/llama-server.exe")
$baseBlob = Resolve-VcorePath $env:VCORE_LLM_BASE_MODEL `
    (Join-Path $HOME ".ollama/models/blobs/sha256-b709d81508a078a686961de6ca07a953b895d9b286c46e17f00fb267f4f2d297")
$adapter = Resolve-VcorePath $env:VCORE_LLM_ADAPTER `
    (Join-Path $repo "docs/sft/integrated/data/vcore-path-action-router-adapter-f16.gguf")
$log         = Join-Path $repo "Intermediate/llama-server-8080.log"
$healthUrl   = "http://127.0.0.1:8080/health"

function Test-LlamaHealthy {
    try { return (Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2).status -eq "ok" }
    catch { return $false }
}

if ($Force) {
    Write-Host "[start-demo] -Force: stopping any running llama-server to guarantee the correct model..."
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

if (Test-LlamaHealthy) {
    Write-Host "[start-demo] llama-server already healthy on :8080."
} else {
    $missing = @($llamaServer, $baseBlob, $adapter) | Where-Object { -not (Test-Path -LiteralPath $_) }
    if ($missing.Count -gt 0) {
        Write-Host "[start-demo] Missing required LLM runtime file(s):" -ForegroundColor Red
        $missing | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        if ($missing -contains $llamaServer) {
            Write-Host "[start-demo] Build it with: powershell -ExecutionPolicy Bypass -File Scripts/BuildLlamaServer.ps1" -ForegroundColor Yellow
        }
        Write-Host "[start-demo] Paths can be overridden with VCORE_LLAMA_SERVER, VCORE_LLM_BASE_MODEL, and VCORE_LLM_ADAPTER." -ForegroundColor Yellow
        throw "Missing required VCORE LLM runtime file(s)."
    }
    Write-Host "[start-demo] launching llama-server (base + routing LoRA, adapter off by default)..."
    # --lora-init-without-apply: the adapter is loaded but applied per-request via the
    # 'lora' scale the backend sends (1.0 routing / 0.0 chat+report).
    $args = @(
        "-m", $baseBlob,
        "--lora", $adapter, "--lora-init-without-apply",
        "--host", "0.0.0.0", "--port", "8080",
        "-ngl", "99", "-c", "8192", "--jinja", "--reasoning", "off", "--reasoning-budget", "0"
    )
    Start-Process -FilePath $llamaServer -ArgumentList $args `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden

    Write-Host "[start-demo] waiting for :8080 to become healthy..."
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        if (Test-LlamaHealthy) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "llama-server did not become healthy in time. See $log" }
    Write-Host "[start-demo] llama-server healthy on :8080."
}

$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $dockerCommand) { throw "docker.exe was not found on PATH. Install or start Docker Desktop." }
& $dockerCommand.Source info --format "{{.ServerVersion}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The Docker engine is unavailable. Start Docker Desktop, then retry." }

Push-Location $PSScriptRoot
try {
    if ($Build) {
        Write-Host "[start-demo] docker compose up --build -d ..."
        & $dockerCommand.Source compose up --build -d
    } else {
        Write-Host "[start-demo] docker compose up -d ..."
        & $dockerCommand.Source compose up -d
    }
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

Write-Host "[start-demo] done. Backend: http://localhost:8000  |  Web: http://localhost:5199"
Write-Host "[start-demo] LLM status: http://localhost:8000/llm/status (waits & self-heals if the model server lags)."
