@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-dev.ps1" %*
if errorlevel 1 (
  echo.
  echo Development environment check failed. Check the messages above.
  pause
  exit /b 1
)
echo.
echo Development environment check complete.
pause
