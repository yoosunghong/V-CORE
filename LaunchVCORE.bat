@echo off
setlocal

rem ============================================================================
rem  VCORE single-entry launcher
rem  Brings up, in order:
rem    1. LLM + web stack  (host llama-server :8080 + docker compose)  via web\start-demo.ps1
rem    2. Pixel Streaming 2 Signalling Server (streamer :8888 / player :8880)
rem    3. The PACKAGED UE5 client (Packaged\Windows\VCORE.exe), streaming to :8888
rem
rem  Build the package first with package.bat (or the editor Platforms > Windows
rem  > Package Project menu). Override the exe location with VCORE_PACKAGED_EXE.
rem ============================================================================

set "PROJECT_ROOT=%~dp0"
set "START_DEMO=%PROJECT_ROOT%web\start-demo.ps1"
set "SIGNALLING_HELPER=%PROJECT_ROOT%Scripts\StartPixelStreaming2SignallingServer.bat"
set "PIXEL_STREAMING_URL=ws://127.0.0.1:8888"
set "PLAYER_URL=http://127.0.0.1:8880"

if not defined VCORE_PACKAGED_EXE set "VCORE_PACKAGED_EXE=%PROJECT_ROOT%Packaged\Windows\VCORE.exe"

echo.
echo VCORE Launcher (packaged client + Pixel Streaming + LLM backend)
echo ===============================================================
echo.

if not exist "%VCORE_PACKAGED_EXE%" (
  echo ERROR: Packaged UE5 client was not found:
  echo   %VCORE_PACKAGED_EXE%
  echo.
  echo Build a package first:
  echo   package.bat
  echo or set VCORE_PACKAGED_EXE to the VCORE.exe of an existing package.
  echo.
  pause
  exit /b 1
)

if not exist "%START_DEMO%" (
  echo ERROR: web\start-demo.ps1 was not found at "%START_DEMO%".
  pause
  exit /b 1
)

if not exist "%SIGNALLING_HELPER%" (
  echo ERROR: Signalling Server helper was not found at "%SIGNALLING_HELPER%".
  pause
  exit /b 1
)

echo [1/3] Bringing up the LLM + web stack (host llama-server :8080 + docker compose)...
echo.
powershell -ExecutionPolicy Bypass -File "%START_DEMO%" -Force
if errorlevel 1 (
  echo.
  echo ERROR: LLM/web stack bring-up failed. Aborting before UE5 launch.
  pause
  exit /b 1
)
echo.

echo [2/3] Starting Pixel Streaming 2 Signalling Server...
start "VCORE PS2 Signalling Server" cmd /k call "%SIGNALLING_HELPER%"

echo       Waiting for streamer WebSocket port 8888...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $c=New-Object Net.Sockets.TcpClient; $iar=$c.BeginConnect('127.0.0.1',8888,$null,$null); if($iar.AsyncWaitHandle.WaitOne(500)){ $c.EndConnect($iar); $c.Close(); exit 0 }; $c.Close() } catch {}; Start-Sleep -Milliseconds 500 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo.
  echo WARNING: Port 8888 did not open within 45 seconds.
  echo The UE5 client will still launch, but Pixel Streaming may not connect.
  echo Check the "VCORE PS2 Signalling Server" window for errors.
  echo.
) else (
  echo       Signalling Server is listening on 127.0.0.1:8888.
)
echo.

echo [3/3] Launching packaged UE5 client:
echo   %VCORE_PACKAGED_EXE%
echo   -PixelStreamingURL=%PIXEL_STREAMING_URL%
echo.
start "VCORE UE5 Packaged Pixel Streaming" "%VCORE_PACKAGED_EXE%" /Game/GAME/Maps/Warehouse -RenderOffscreen -ResX=1280 -ResY=720 -ForceRes -AudioMixer -log -PixelStreamingURL=%PIXEL_STREAMING_URL%

echo Done.
echo   Pixel Streaming player page : %PLAYER_URL%
echo   Web overlay / operator app  : http://localhost:5199
echo   Backend API                 : http://localhost:8000
echo.
endlocal
