@echo off
setlocal

set "UE_ROOT=C:\Program Files\Epic Games\UE_5.7"
set "UE_EDITOR=%UE_ROOT%\Engine\Binaries\Win64\UnrealEditor.exe"
set "PROJECT_FILE=%~dp0VCORE.uproject"

if not defined VCORE_PIXEL_STREAMING_URL set "VCORE_PIXEL_STREAMING_URL=wss://streamer.v-core.yoosung.dev"

if not exist "%UE_EDITOR%" (
  echo ERROR: UnrealEditor.exe was not found at "%UE_EDITOR%".
  exit /b 1
)

if not exist "%PROJECT_FILE%" (
  echo ERROR: Project file was not found at "%PROJECT_FILE%".
  exit /b 1
)

echo Publishing UE5 Pixel Streaming to:
echo   %VCORE_PIXEL_STREAMING_URL%
echo.

start "VCORE UE5 Cloud Pixel Streaming" "%UE_EDITOR%" "%PROJECT_FILE%" /Game/GAME/Maps/Warehouse -game -RenderOffscreen -ResX=1280 -ResY=720 -ForceRes -AudioMixer -log -PixelStreamingURL=%VCORE_PIXEL_STREAMING_URL%

echo UE5 started. Player URL:
echo   https://stream.v-core.yoosung.dev
endlocal
