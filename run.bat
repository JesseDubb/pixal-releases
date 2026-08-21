@echo off
setlocal

rem Unbuffered, so a crashing sidecar's last words reach logs\sidecar.log
rem instead of dying in a stdio buffer.
set "PYTHONUNBUFFERED=1"

set "PIXAL_ROOT=%~dp0"
set "PIXAL_PY_EXE="

rem An explicit interpreter always wins.
if defined PIXAL_PYTHON (
  if not exist "%PIXAL_PYTHON%" (
    echo [pixal] PIXAL_PYTHON does not point to an existing interpreter:
    echo [pixal]   "%PIXAL_PYTHON%"
    exit /b 1
  )
  set "PIXAL_PY_EXE=%PIXAL_PYTHON%"
)

rem Written by the installer when Pixal runs on an interpreter it did not create -
rem normally the ComfyUI portable's python_embeded, from a Pixal folder that is
rem NOT inside that portable. An embeddable python cannot make a .venv and
rem pixal.vbs calls this script with a bare environment, so the choice has to
rem live on disk. One line, the full path to python.exe.
if not defined PIXAL_PY_EXE if exist "%PIXAL_ROOT%.pixal_python" (
  for /f "usebackq delims=" %%I in ("%PIXAL_ROOT%.pixal_python") do (
    if not defined PIXAL_PY_EXE if exist "%%~I" set "PIXAL_PY_EXE=%%~I"
  )
)

rem Normal standalone installation.
if not defined PIXAL_PY_EXE if exist "%PIXAL_ROOT%.venv\Scripts\python.exe" (
  set "PIXAL_PY_EXE=%PIXAL_ROOT%.venv\Scripts\python.exe"
)

rem ComfyUI Windows portable layout: ComfyUI\pixal_dm -> python_embeded.
if not defined PIXAL_PY_EXE if exist "%PIXAL_ROOT%..\..\python_embeded\python.exe" (
  set "PIXAL_PY_EXE=%PIXAL_ROOT%..\..\python_embeded\python.exe"
)

if not defined PIXAL_PY_EXE (
  echo [pixal] No Python interpreter was found.
  echo [pixal] Create .venv, set PIXAL_PYTHON, or use the ComfyUI portable layout.
  exit /b 1
)

pushd "%PIXAL_ROOT%" >nul
"%PIXAL_PY_EXE%" "%PIXAL_ROOT%server.py" %*
set "PIXAL_EXIT=%ERRORLEVEL%"
popd >nul
exit /b %PIXAL_EXIT%
