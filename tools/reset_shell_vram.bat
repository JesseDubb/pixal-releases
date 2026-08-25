@echo off
REM Reclaim desktop VRAM: restart Explorer + DWM (Windows respawns dwm.exe).
REM Expect a screen flash; every Explorer window closes. Do not run mid-render.
REM Source: r/StableDiffusion PSA, kept by Jesse 2026-08-25 (dwm sat on 2.5 GB).
net session >nul 2>&1
if %errorlevel% NEQ 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo [*] Stopping Explorer...
taskkill /f /im explorer.exe >nul 2>&1
echo [*] Restarting Desktop Window Manager...
taskkill /f /im dwm.exe >nul 2>&1
echo [*] Waiting for services to settle...
timeout /t 2 /nobreak >nul
echo [*] Starting Explorer...
start explorer.exe
echo [ok] Done.
exit /b
