@echo off
setlocal

for %%I in ("%~dp0..") do set "PIXAL_ROOT=%%~fI"
set "PIXAL_ESBUILD=%PIXAL_ROOT%\node_modules\.bin\esbuild.cmd"

if not exist "%PIXAL_ESBUILD%" (
  echo [pixal] Frontend dependencies are not installed.
  echo [pixal] Run "npm install" from "%PIXAL_ROOT%".
  exit /b 1
)

call "%PIXAL_ESBUILD%" "%~dp0src\app.jsx" --bundle --format=esm --external:/vendor/* --outfile="%~dp0app.js" --jsx=automatic --minify
set "PIXAL_BUILD_EXIT=%ERRORLEVEL%"

if not "%PIXAL_BUILD_EXIT%"=="0" (
  endlocal & exit /b %PIXAL_BUILD_EXIT%
)

rem The stamp hashes app.js AND index.html AND the manifest AND the vendored
rem three.module.js, so a vendor bump rotates the cache too. Hashing app.js
rem alone meant a changed favicon link, title or manifest icon shipped under the
rem OLD cache name, so the service worker kept serving the stale shell and the
rem change was invisible until a hard reload (2026-08-17, chasing a favicon).
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $dir = '%~dp0'; $swPath = $dir + 'sw.js'; $parts = @('app.js','index.html','manifest.webmanifest','vendor\three.module.js') | ForEach-Object { (Get-FileHash -LiteralPath ($dir + $_) -Algorithm SHA256).Hash }; $joined = $parts -join ''; $sha = [System.Security.Cryptography.SHA256]::Create(); $hash = ((([System.BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($joined)))) -replace '-','')).Substring(0, 8).ToLowerInvariant(); $utf8NoBom = [System.Text.UTF8Encoding]::new($false); $contents = [System.IO.File]::ReadAllText($swPath); $pattern = 'const CACHE = \x22pixal-dm-[^\x22]*\x22;'; $found = [regex]::Matches($contents, $pattern); if ($found.Count -ne 1) { throw 'Expected exactly one cache declaration.' }; $replacement = 'const CACHE = ' + [char]34 + 'pixal-dm-' + $hash + [char]34 + ';'; $updated = [regex]::Replace($contents, $pattern, $replacement, 1); [System.IO.File]::WriteAllText($swPath, $updated, $utf8NoBom)" >nul 2>nul
if errorlevel 1 (
  echo [pixal] Failed to stamp the service-worker cache name.
  endlocal & exit /b 1
)

endlocal & exit /b 0
