@echo off
setlocal

set "SCRIPT_ROOT=%~dp0"
for %%I in ("%SCRIPT_ROOT%..") do set "PROJECT_ROOT=%%~fI"

if not "%~1"=="" set "VCORE_PACKAGED_EXE=%~f1"
if not defined VCORE_PACKAGED_EXE set "VCORE_PACKAGED_EXE=%PROJECT_ROOT%\Packaged\Windows\VCORE.exe"
if not defined VCORE_PIXEL_STREAMING_URL set "VCORE_PIXEL_STREAMING_URL=ws://127.0.0.1:8888"

if not exist "%VCORE_PACKAGED_EXE%" (
  echo ERROR: Packaged UE5 client was not found:
  echo   %VCORE_PACKAGED_EXE%
  echo Package the project first, pass the executable as the first argument,
  echo or set VCORE_PACKAGED_EXE.
  exit /b 1
)

echo Starting packaged UE5 client...
echo   Executable      : %VCORE_PACKAGED_EXE%
echo   Streaming URL  : %VCORE_PIXEL_STREAMING_URL%

start "VCORE UE5" "%VCORE_PACKAGED_EXE%" /Game/GAME/Maps/Warehouse -RenderOffscreen -ResX=1280 -ResY=720 -ForceRes -AudioMixer -log -PixelStreamingURL=%VCORE_PIXEL_STREAMING_URL%
exit /b 0
