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

rem The installer records its private venv/runtime as an app-relative path.
rem Legacy absolute choices still work. Relative paths avoid decoding non-ASCII
rem account names from a UTF-8 file through cmd.exe's OEM code page.
if not defined PIXAL_PY_EXE if exist "%PIXAL_ROOT%.pixal_python" (
  for /f "usebackq delims=" %%I in ("%PIXAL_ROOT%.pixal_python") do (
    if not defined PIXAL_PY_EXE if exist "%PIXAL_ROOT%%%~I" set "PIXAL_PY_EXE=%PIXAL_ROOT%%%~I"
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
