@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pull.ps1" %*
if errorlevel 1 (
  echo.
  echo Pull failed. Check the messages above.
  pause
  exit /b 1
)
echo.
echo Pull complete.
pause
