@echo off
setlocal

set "FORCE_ARG="
if /i "%~1"=="--force" set "FORCE_ARG=-Force"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0StartLlamaBackend.ps1" %FORCE_ARG%
exit /b %ERRORLEVEL%
