@echo off
setlocal

set "SCRIPT_ROOT=%~dp0"
for %%I in ("%SCRIPT_ROOT%..") do set "PROJECT_ROOT=%%~fI"
set "PS_WEB_ROOT=%PROJECT_ROOT%\PixelStreaming2WebServers"
set "SIGNALLING_ROOT=%PS_WEB_ROOT%\SignallingWebServer"
set "SIGNALLING_DIST=%SIGNALLING_ROOT%\dist\index.js"
set "SIGNALLING_WWW=%SIGNALLING_ROOT%\www"
set "NPM_CACHE=%PROJECT_ROOT%\.npm-cache"

if not exist "%SIGNALLING_ROOT%\package.json" (
  echo ERROR: Pixel Streaming Signalling Server was not found:
  echo   %SIGNALLING_ROOT%
  exit /b 1
)

where node.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: node.exe was not found on PATH.
  exit /b 1
)

if not exist "%SIGNALLING_DIST%" (
  echo Pixel Streaming server is not built. Installing and building it now...
  pushd "%PS_WEB_ROOT%"
  set "npm_config_cache=%NPM_CACHE%"
  call npm.cmd install
  if errorlevel 1 goto :build_failure
  pushd Common
  call npm.cmd run build:cjs
  if errorlevel 1 goto :build_failure
  popd
  pushd Signalling
  call npm.cmd run build:cjs
  if errorlevel 1 goto :build_failure
  popd
  pushd Frontend\library
  call npm.cmd run build:esm
  if errorlevel 1 goto :build_failure
  popd
  pushd Frontend\ui-library
  call npm.cmd run build:esm
  if errorlevel 1 goto :build_failure
  popd
  pushd Frontend\implementations\typescript
  call npm.cmd run build:dev
  if errorlevel 1 goto :build_failure
  popd
  pushd SignallingWebServer
  call npm.cmd run build
  if errorlevel 1 goto :build_failure
  popd
  popd
)

echo Starting Pixel Streaming signalling server...
echo   Streamer WebSocket : ws://127.0.0.1:8888
echo   Player             : http://127.0.0.1:8880
pushd "%SIGNALLING_ROOT%"
node dist\index.js --serve --console_messages verbose --log_config --streamer_port 8888 --player_port 8880 --http_root "%SIGNALLING_WWW%"
set "RESULT=%ERRORLEVEL%"
popd
exit /b %RESULT%

:build_failure
set "RESULT=%ERRORLEVEL%"
popd
echo ERROR: Pixel Streaming server build failed with exit code %RESULT%.
exit /b %RESULT%
