param(
    [string]$SourceDir = $(if ($env:VCORE_LLAMA_SOURCE) { $env:VCORE_LLAMA_SOURCE } else { "C:\tmp\llama.cpp" }),
    [string]$BuildDir,
    [string]$CudaArchitectures = $(if ($env:VCORE_CUDA_ARCHITECTURES) { $env:VCORE_CUDA_ARCHITECTURES } else { "89" })
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
if (-not $BuildDir) { $BuildDir = Join-Path $repo "Intermediate\llama-build" }

$cmakeCommand = Get-Command cmake.exe -ErrorAction SilentlyContinue
$cmake = if ($cmakeCommand) { $cmakeCommand.Source } else { "C:\Program Files\CMake\bin\cmake.exe" }
if (-not (Test-Path -LiteralPath $cmake)) { throw "cmake.exe was not found. Install CMake or add it to PATH." }
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "CMakeLists.txt"))) {
    throw "llama.cpp source was not found at '$SourceDir'. Set VCORE_LLAMA_SOURCE or pass -SourceDir."
}

$cudaRoot = $env:CUDA_PATH
if (-not $cudaRoot) {
    $cudaRoot = Get-ChildItem "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $cudaRoot -or -not (Test-Path -LiteralPath (Join-Path $cudaRoot "bin\nvcc.exe"))) {
    throw "A CUDA Toolkit installation was not found. Install CUDA or set CUDA_PATH."
}

Write-Host "[llama-build] Source : $SourceDir"
Write-Host "[llama-build] Output : $BuildDir"
Write-Host "[llama-build] CUDA   : $cudaRoot (architecture $CudaArchitectures)"

& $cmake --fresh -B $BuildDir -S $SourceDir `
    -DGGML_CUDA=ON `
    "-DCMAKE_CUDA_ARCHITECTURES=$CudaArchitectures" `
    -T "cuda=$cudaRoot"
if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed with exit code $LASTEXITCODE." }

& $cmake --build $BuildDir --config Release --target llama-server --parallel
if ($LASTEXITCODE -ne 0) { throw "llama-server build failed with exit code $LASTEXITCODE." }

$server = Join-Path $BuildDir "bin\Release\llama-server.exe"
if (-not (Test-Path -LiteralPath $server)) { throw "Build completed but llama-server.exe was not found at '$server'." }

Write-Host "[llama-build] Verifying CUDA device discovery..."
& $server --list-devices
if ($LASTEXITCODE -ne 0) { throw "llama-server CUDA verification failed with exit code $LASTEXITCODE." }

Write-Host "[llama-build] Ready: $server"
