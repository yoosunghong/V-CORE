@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "SIGNALLING_ROOT=%PROJECT_ROOT%\PixelStreaming2WebServers\SignallingWebServer"
set "SIGNALLING_WWW=%SIGNALLING_ROOT%\www"
set "NPM_CACHE=%PROJECT_ROOT%\.npm-cache"

cd /d "%SIGNALLING_ROOT%"
set "npm_config_cache=%NPM_CACHE%"

node dist\index.js --serve --console_messages verbose --log_config --streamer_port 8888 --player_port 8880 --http_root "%SIGNALLING_WWW%"
