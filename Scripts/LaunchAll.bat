@echo off
setlocal

rem Starts the complete local VCORE runtime in dependency order:
rem llama backend -> web stack -> Pixel Streaming -> packaged UE5 client.

set "SCRIPT_ROOT=%~dp0"
for %%I in ("%SCRIPT_ROOT%..") do set "PROJECT_ROOT=%%~fI"

echo.
echo VCORE All-in-One Launcher
echo =========================
echo.

echo [1/4] Starting llama LLM backend...
call "%SCRIPT_ROOT%LaunchLlamaBackend.bat"
if errorlevel 1 goto :failure

echo.
echo [2/4] Starting web services...
call "%SCRIPT_ROOT%LaunchWeb.bat"
if errorlevel 1 goto :failure

echo.
echo [3/4] Starting Pixel Streaming signalling server...
start "VCORE Pixel Streaming" cmd.exe /k call "%SCRIPT_ROOT%LaunchPixelStreaming.bat"

echo       Waiting for streamer port 8888...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $client=[Net.Sockets.TcpClient]::new(); $client.Connect('127.0.0.1',8888); $client.Dispose(); exit 0 } catch { if ($client) { $client.Dispose() } }; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo ERROR: Pixel Streaming did not open port 8888 within 45 seconds.
  echo Check the "VCORE Pixel Streaming" window for the server error.
  goto :failure
)

echo.
echo [4/4] Starting packaged UE5 client...
call "%SCRIPT_ROOT%LaunchUE5.bat" %*
if errorlevel 1 goto :failure

echo.
echo VCORE is running.
echo   Operator web app : http://localhost:5199
echo   Backend API      : http://localhost:8000
echo   LLM backend      : http://localhost:8080
echo   Streaming player : http://localhost:8880
exit /b 0

:failure
echo.
echo VCORE startup failed. See the error above.
exit /b 1
