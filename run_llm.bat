@echo off
REM MANUAL FALLBACK - Pixal normally spawns this server itself when the
REM "Local (uncensored)" preset is active (see ensure_local_llm in server.py).
REM Start by hand only to run a model/flags combo the settings UI can't express;
REM the sidecar detects an external :8191 server and uses it as-is.
REM KMP guard: some Windows CUDA llama.cpp builds otherwise clash with Torch's OMP runtime.
setlocal
set KMP_DUPLICATE_LIB_OK=TRUE
set "PIXAL_BASE_PATH=%PATH%"

set "PIXAL_LLM_PY="
if defined PIXAL_LLM_PYTHON goto explicit_llm_python
goto automatic_llm_python

:explicit_llm_python
if exist "%PIXAL_LLM_PYTHON%" goto probe_explicit_llm_python
echo [pixal] PIXAL_LLM_PYTHON does not point to an existing interpreter:
echo [pixal]   "%PIXAL_LLM_PYTHON%"
exit /b 1

:probe_explicit_llm_python
call :try_python "%PIXAL_LLM_PYTHON%"
if defined PIXAL_LLM_PY goto llm_python_ready
echo [pixal] PIXAL_LLM_PYTHON cannot import llama_cpp.server:
echo [pixal]   "%PIXAL_LLM_PYTHON%"
exit /b 1

:automatic_llm_python
if defined PIXAL_PYTHON call :try_python "%PIXAL_PYTHON%"
if not defined PIXAL_LLM_PY call :try_python "%~dp0.venv\Scripts\python.exe"
if not defined PIXAL_LLM_PY call :try_python "%~dp0..\..\python_embeded\python.exe"

:llm_python_ready

set "PIXAL_LLM_FILE=%PIXAL_LLM_MODEL%"
if not defined PIXAL_LLM_FILE if exist "%~dp0..\models\LLM\GGUF\Josiefied-Qwen3-4B-abliterated-v2.Q8_0.gguf" set "PIXAL_LLM_FILE=%~dp0..\models\LLM\GGUF\Josiefied-Qwen3-4B-abliterated-v2.Q8_0.gguf"

if not defined PIXAL_LLM_PY (
  echo [pixal] No Python interpreter with llama_cpp.server was found.
  echo [pixal] Set PIXAL_LLM_PYTHON or install llama-cpp-python in Pixal or ComfyUI portable.
  exit /b 1
)
if not defined PIXAL_LLM_FILE (
  echo [pixal] Set PIXAL_LLM_MODEL to the full path of a chat-capable GGUF.
  exit /b 1
)

REM GPU layers for the brain: PIXAL_LLM_GPU_LAYERS overrides (0 = CPU), -1 = all.
if not defined PIXAL_LLM_GPU_LAYERS set "PIXAL_LLM_GPU_LAYERS=-1"

"%PIXAL_LLM_PY%" -m llama_cpp.server ^
  --model "%PIXAL_LLM_FILE%" ^
  --n_gpu_layers %PIXAL_LLM_GPU_LAYERS% --n_ctx 16384 --host 127.0.0.1 --port 8191
exit /b %ERRORLEVEL%

:try_python
if defined PIXAL_LLM_PY exit /b 0
if not exist "%~1" exit /b 0
set "PATH=%PIXAL_BASE_PATH%"
for %%I in ("%~1") do set "PIXAL_CANDIDATE_HOME=%%~dpI"
if /I "%PIXAL_CANDIDATE_HOME:~-8%"=="Scripts\" for %%I in ("%PIXAL_CANDIDATE_HOME%..") do set "PIXAL_CANDIDATE_HOME=%%~fI\"
if exist "%PIXAL_CANDIDATE_HOME%Lib\site-packages\torch\lib" set "PATH=%PIXAL_CANDIDATE_HOME%Lib\site-packages\torch\lib;%PIXAL_BASE_PATH%"
"%~1" -c "import llama_cpp.server" >nul 2>&1
if errorlevel 1 goto try_python_failed
set "PIXAL_LLM_PY=%~1"
exit /b 0

:try_python_failed
set "PATH=%PIXAL_BASE_PATH%"
exit /b 0
