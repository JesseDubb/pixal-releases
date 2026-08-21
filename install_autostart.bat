@echo off
setlocal

set "PIXAL_ROOT=%~dp0"
set "PIXAL_STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "PIXAL_SHORTCUT=%PIXAL_STARTUP%\Pixal.lnk"

powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut($env:PIXAL_SHORTCUT); $shortcut.TargetPath=(Join-Path $env:WINDIR 'System32\wscript.exe'); $shortcut.Arguments=([char]34 + (Join-Path $env:PIXAL_ROOT 'pixal.vbs') + [char]34 + ' boot'); $shortcut.WorkingDirectory=$env:PIXAL_ROOT; $shortcut.Save()"
if errorlevel 1 (
    echo [pixal] Failed to create startup shortcut "%PIXAL_SHORTCUT%".
    exit /b 1
)

echo [pixal] Startup shortcut installed: "%PIXAL_SHORTCUT%"
exit /b 0
