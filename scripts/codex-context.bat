@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0codex-context.ps1" %*
if errorlevel 1 (
  echo.
  echo Failed to prepare Codex context. Check the messages above.
  pause
  exit /b 1
)
echo.
echo Codex handoff prompt copied to clipboard.
pause
