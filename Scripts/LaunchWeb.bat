@echo off
setlocal

set "SCRIPT_ROOT=%~dp0"
for %%I in ("%SCRIPT_ROOT%..") do set "PROJECT_ROOT=%%~fI"
set "WEB_ROOT=%PROJECT_ROOT%\web"

where docker.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: docker.exe was not found on PATH. Install or start Docker Desktop.
  exit /b 1
)

docker info --format "{{.ServerVersion}}" >nul 2>nul
if errorlevel 1 (
  echo ERROR: The Docker engine is unavailable. Start Docker Desktop, then retry.
  exit /b 1
)

pushd "%WEB_ROOT%"
if /i "%~1"=="--build" (
  echo Starting web services with an image rebuild...
  docker compose up --build -d
) else (
  echo Starting web services...
  docker compose up -d
)
set "RESULT=%ERRORLEVEL%"
popd

if not "%RESULT%"=="0" (
  echo ERROR: docker compose failed with exit code %RESULT%.
  exit /b %RESULT%
)

echo Web services are running.
echo   Operator web app : http://localhost:5199
echo   Backend API      : http://localhost:8000
exit /b 0
