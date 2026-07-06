@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push.ps1" %*
if errorlevel 1 (
  echo.
  echo Upload failed. Check the messages above.
  pause
  exit /b 1
)
echo.
echo Upload complete.
pause
