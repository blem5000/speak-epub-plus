@echo off
REM speak.cmd - launcher for the self-contained Speak EPUB CLI (Windows).
REM
REM 1. a cached Python runtime (downloaded once) is used when present
REM 2. otherwise any system Python starts speak.py, which fetches the runtime
REM 3. without any Python the runtime is downloaded with PowerShell
setlocal
set "HERE=%~dp0"
set "RUNTIME_DIR=%LOCALAPPDATA%\speak-epub\runtime"

if not exist "%HERE%runtime.json" (
  echo Missing "%HERE%runtime.json" - this is not a Speak EPUB CLI package.
  exit /b 1
)

REM --- 1) the cached runtime ------------------------------------------------
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-Content -Raw '%HERE%runtime.json' | ConvertFrom-Json).hash"`) do set "HASH=%%H"
set "CACHED=%RUNTIME_DIR%\%HASH%\python\python.exe"
if exist "%CACHED%" (
  "%CACHED%" "%HERE%speak.py" %*
  exit /b %ERRORLEVEL%
)

REM --- 2) any system Python (speak.py downloads the runtime) ----------------
where py >nul 2>&1 && (
  py -3 "%HERE%speak.py" %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1 && (
  python "%HERE%speak.py" %*
  exit /b %ERRORLEVEL%
)

REM --- 3) no Python at all: fetch the runtime with PowerShell ---------------
echo No Python found - downloading the Speak EPUB runtime (one-time, ~40 MB)...
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "(Get-Content -Raw '%HERE%runtime.json' | ConvertFrom-Json).release_url"`) do set "BASE=%%U"
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "(Get-Content -Raw '%HERE%runtime.json' | ConvertFrom-Json).asset"`) do set "ASSET=%%A"
if not defined BASE (echo The runtime descriptor is broken. exit /b 1)
if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; $zip=Join-Path $env:TEMP 'speak-epub-runtime.zip';" ^
  "Invoke-WebRequest -Uri ('%BASE%/' + '%ASSET%') -OutFile $zip;" ^
  "if (Test-Path '%RUNTIME_DIR%\%HASH%') { Remove-Item '%RUNTIME_DIR%\%HASH%' -Recurse -Force };" ^
  "Expand-Archive -LiteralPath $zip -DestinationPath '%RUNTIME_DIR%\%HASH%' -Force;" ^
  "Remove-Item $zip -Force"
if not exist "%CACHED%" (
  echo The runtime download failed.
  exit /b 1
)
"%CACHED%" "%HERE%speak.py" %*
exit /b %ERRORLEVEL%
