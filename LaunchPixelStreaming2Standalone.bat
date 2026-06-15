@echo off
setlocal

set "UE_ROOT=C:\Program Files\Epic Games\UE_5.7"
set "UE_EDITOR=%UE_ROOT%\Engine\Binaries\Win64\UnrealEditor.exe"
set "PROJECT_FILE=%~dp0VCORE.uproject"
set "PROJECT_ROOT=%~dp0"
set "PS_WEB_ROOT=%PROJECT_ROOT%PixelStreaming2WebServers"
set "SIGNALLING_ROOT=%PS_WEB_ROOT%\SignallingWebServer"
set "SIGNALLING_DIST=%SIGNALLING_ROOT%\dist\index.js"
set "SIGNALLING_WWW=%SIGNALLING_ROOT%\www"
set "NPM_CACHE=%~dp0.npm-cache"
set "SIGNALLING_HELPER=%PROJECT_ROOT%Scripts\StartPixelStreaming2SignallingServer.bat"
set "PIXEL_STREAMING_URL=ws://127.0.0.1:8888"
set "PLAYER_URL=http://127.0.0.1:8880"

echo.
echo VCORE Pixel Streaming 2 Standalone Launcher
echo ===========================================
echo.

if not exist "%UE_EDITOR%" (
  echo ERROR: UnrealEditor.exe was not found:
  echo   %UE_EDITOR%
  echo.
  pause
  exit /b 1
)

if not exist "%PROJECT_FILE%" (
  echo ERROR: Project file was not found:
  echo   %PROJECT_FILE%
  echo.
  pause
  exit /b 1
)

if not exist "%SIGNALLING_ROOT%\package.json" (
  echo ERROR: Pixel Streaming Signalling Server was not found.
  echo Expected:
  echo   %SIGNALLING_ROOT%\package.json
  echo.
  echo Copy or download the UE 5.6 Pixel Streaming 2 WebServers into:
  echo   %PS_WEB_ROOT%
  echo.
  pause
  exit /b 1
)

if not exist "%SIGNALLING_DIST%" (
  echo Signalling Server build output is missing. Installing and building local server...
  echo.
  pushd "%PS_WEB_ROOT%"
  set "npm_config_cache=%NPM_CACHE%"
  call npm.cmd install
  if errorlevel 1 (
    popd
    echo.
    echo ERROR: npm install failed.
    pause
    exit /b 1
  )
  cd Common
  call npm.cmd run build:cjs
  cd ..\Signalling
  call npm.cmd run build:cjs
  cd ..\Frontend\library
  call npm.cmd run build:esm
  cd ..\ui-library
  call npm.cmd run build:esm
  cd ..\implementations\typescript
  call npm.cmd run build:dev
  cd ..\..\..\SignallingWebServer
  call npm.cmd run build
  if errorlevel 1 (
    popd
    echo.
    echo ERROR: Signalling Server build failed.
    pause
    exit /b 1
  )
  popd
)

echo Starting Pixel Streaming 2 Signalling Server...
start "VCORE PS2 Signalling Server" cmd /k call "%SIGNALLING_HELPER%"

echo Waiting for streamer WebSocket port 8888...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $c=New-Object Net.Sockets.TcpClient; $iar=$c.BeginConnect('127.0.0.1',8888,$null,$null); if($iar.AsyncWaitHandle.WaitOne(500)){ $c.EndConnect($iar); $c.Close(); exit 0 }; $c.Close() } catch {}; Start-Sleep -Milliseconds 500 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo.
  echo WARNING: Port 8888 did not open within 45 seconds.
  echo The UE Standalone game will still be launched, but Pixel Streaming may not connect.
  echo Check the "VCORE PS2 Signalling Server" window for errors.
  echo.
) else (
  echo Signalling Server is listening on 127.0.0.1:8888.
)

echo.
echo Launching UE5 Standalone game with:
echo   -PixelStreamingURL=%PIXEL_STREAMING_URL%
echo.

start "VCORE UE5 Standalone Pixel Streaming" "%UE_EDITOR%" "%PROJECT_FILE%" /Game/GAME/Maps/Warehouse -game -RenderOffscreen -ResX=1280 -ResY=720 -ForceRes -AudioMixer -log -PixelStreamingURL=%PIXEL_STREAMING_URL%

echo Done. Open http://localhost:5199 after the Standalone game connects.
echo Pixel Streaming player page:
echo   %PLAYER_URL%
echo.
pause
