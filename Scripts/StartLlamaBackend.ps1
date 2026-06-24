param([switch]$Force)

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
$log = Join-Path $repo "Intermediate/llama-server-8080.log"
$healthUrl = "http://127.0.0.1:8080/health"

function Test-LlamaHealthy {
    try { return (Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2).status -eq "ok" }
    catch { return $false }
}

if ($Force) {
    Write-Host "[llama] stopping existing llama-server processes..."
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
}

if (Test-LlamaHealthy) {
    Write-Host "[llama] backend is already healthy on :8080."
    exit 0
}

$missing = @($llamaServer, $baseBlob, $adapter) | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing.Count -gt 0) {
    Write-Host "[llama] Missing required runtime files:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    if ($missing -contains $llamaServer) {
        Write-Host "Build it with Scripts\BuildLlamaServer.ps1." -ForegroundColor Yellow
    }
    throw "Missing required VCORE llama runtime files."
}

$arguments = @(
    "-m", $baseBlob,
    "--lora", $adapter, "--lora-init-without-apply",
    "--host", "0.0.0.0", "--port", "8080",
    "-ngl", "99", "-c", "8192", "--jinja",
    "--reasoning", "off", "--reasoning-budget", "0"
)

Write-Host "[llama] starting backend on :8080..."
Start-Process -FilePath $llamaServer -ArgumentList $arguments `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden

for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if (Test-LlamaHealthy) {
        Write-Host "[llama] backend is healthy on :8080."
        exit 0
    }
    Start-Sleep -Seconds 2
}

throw "llama-server did not become healthy. See '$log' and '$log.err'."
