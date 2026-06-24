@echo off
setlocal

rem ============================================================================
rem  Package the VCORE UE5 client to Packaged\Windows\VCORE.exe
rem  Output is what LaunchVCORE.bat runs. Re-run after content/code changes.
rem
rem  Config: Development (keeps -log console). Pass "shipping" for a Shipping build.
rem ============================================================================

set "UE_ROOT=C:\Program Files\Epic Games\UE_5.7"
set "RUNUAT=%UE_ROOT%\Engine\Build\BatchFiles\RunUAT.bat"
set "PROJECT_FILE=%~dp0VCORE.uproject"
set "ARCHIVE_DIR=%~dp0Packaged"

set "CLIENT_CONFIG=Development"
if /I "%~1"=="shipping" set "CLIENT_CONFIG=Shipping"

if not exist "%RUNUAT%" (
  echo ERROR: RunUAT.bat was not found at "%RUNUAT%".
  echo Edit UE_ROOT in this script if your engine is installed elsewhere.
  pause
  exit /b 1
)

if not exist "%PROJECT_FILE%" (
  echo ERROR: Project file was not found at "%PROJECT_FILE%".
  pause
  exit /b 1
)

echo Packaging VCORE (%CLIENT_CONFIG%) to:
echo   %ARCHIVE_DIR%
echo.

call "%RUNUAT%" BuildCookRun ^
  -project="%PROJECT_FILE%" ^
  -noP4 -platform=Win64 -clientconfig=%CLIENT_CONFIG% ^
  -build -cook -allmaps -stage -pak -archive ^
  -archivedirectory="%ARCHIVE_DIR%"

if errorlevel 1 (
  echo.
  echo ERROR: packaging failed. See the UAT log above.
  pause
  exit /b 1
)

echo.
echo Package complete:
echo   %ARCHIVE_DIR%\Windows\VCORE.exe
echo Launch the full system with: LaunchVCORE.bat
echo.
endlocal
