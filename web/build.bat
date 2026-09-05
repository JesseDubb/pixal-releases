@echo off
setlocal
rem The same build and full-shell cache stamp used by CI on every platform.
node "%~dp0..\tools\build_web.mjs"
set "PIXAL_BUILD_EXIT=%ERRORLEVEL%"
endlocal & exit /b %PIXAL_BUILD_EXIT%
