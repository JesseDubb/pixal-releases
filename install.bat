@echo off
REM Pixal installer - double-click me.
REM
REM Finds a python to run the real installer on, in the order that costs the
REM least: a compatible Python this machine already has, otherwise
REM python.org's 11 MB embeddable build unpacked
REM into install\runtime. The installer itself is stdlib-only for exactly this
REM reason - it has to be able to run on a laptop with nothing on it.
setlocal
title Pixal installer
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" call :try ".venv\Scripts\python.exe"
if not defined PY if exist "install\runtime\python.exe" call :try "install\runtime\python.exe"
if not defined PY call :tryname py -3.12
if not defined PY call :tryname py -3.13
if not defined PY call :tryname python
if defined PY goto run

echo.
echo   No Python on this machine yet. Fetching the small official build
echo   (about 11 MB) into install\runtime - nothing is installed system-wide.
echo.
if not exist "install\runtime" mkdir "install\runtime"
set "PYZIP=install\runtime\python.zip"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
curl -L --fail --progress-bar -o "%PYZIP%" "%PYURL%"
if errorlevel 1 (
  powershell -NoProfile -Command "try{Invoke-WebRequest -Uri '%PYURL%' -OutFile '%PYZIP%'}catch{exit 1}"
)
if not exist "%PYZIP%" goto nopython
powershell -NoProfile -Command "Expand-Archive -Force -LiteralPath '%PYZIP%' -DestinationPath 'install\runtime'"
del "%PYZIP%" >nul 2>&1
call :try "install\runtime\python.exe"
if not defined PY goto nopython

:run
echo   Python: %PY%
echo   Starting the installer. It opens in your browser; leave this window open.
echo.
"%PY%" -X utf8 "install\pixal_install.py"
if errorlevel 1 (
  echo.
  echo   The installer exited with an error. The lines above say why.
  pause
)
exit /b 0

:nopython
echo.
echo   Could not get a Python to run on. Install Python 3.12 from python.org
echo   and run this again.
echo.
pause
exit /b 1

:try
if defined PY exit /b 0
"%~1" -c "import sys,struct;sys.exit(0 if (3,12)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
for %%I in ("%~1") do set "PY=%%~fI"
exit /b 0

:tryname
if defined PY exit /b 0
%* -c "import sys,struct;sys.exit(0 if (3,12)<=sys.version_info[:2]<(3,14) and struct.calcsize('P')==8 else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
for /f "usebackq delims=" %%I in (`%* -c "import sys;print(sys.executable)"`) do set "PY=%%I"
exit /b 0
