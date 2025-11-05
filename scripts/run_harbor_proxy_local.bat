@echo off
setlocal enabledelayedexpansion
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
pushd "%REPO_ROOT%" >nul

if exist .env (
  for /f "usebackq tokens=1,2 delims==" %%A in (`findstr /r "^[A-Za-z0-9_][A-Za-z0-9_]*=.*" .env`) do (
    set "key=%%A"
    set "value=%%B"
    for /f "tokens=* delims= \"" %%V in ("!value!") do set "value=%%V"
    if /i "!key!"=="HARBOR_API_KEY" set "HARBOR_API_KEY=!value!"
    if /i "!key!"=="DEX_PROXY_BASE" set "DEX_PROXY_BASE=!value!"
  )
)

if not defined HARBOR_API_KEY (
  echo [run_harbor_proxy_local] HARBOR_API_KEY is not set. Set it in the environment or .env.>&2
  exit /b 2
)

set "CONFIG_PATH=%REPO_ROOT%\harbor\harbor.config.json"
if not exist "%CONFIG_PATH%" (
  echo [run_harbor_proxy_local] Missing harbor\harbor.config.json.>&2
  echo Create it using the template in TESTING_VASQUEZ_HARBOR.md before launching the proxy.>&2
  exit /b 3
)

for /f "usebackq delims=" %%P in (`set CONFIG_PATH^="%CONFIG_PATH%" ^& python - <<"PY"
import json
import os
from pathlib import Path
cfg = Path(os.environ['CONFIG_PATH'])
with cfg.open() as fh:
    data = json.load(fh)
port = (data.get('server') or {}).get('port', 1958)
print(port)
PY
`) do set "PORT=%%P"

if not defined DEX_PROXY_BASE set "DEX_PROXY_BASE=http://127.0.0.1:%PORT%"

for /f "usebackq delims=" %%L in (`python - <<"PY"
import os
print(len(os.environ.get('HARBOR_API_KEY', '')))
PY
`) do set "HARBOR_API_KEY_LEN=%%L"

echo [run_harbor_proxy_local] Using config: %CONFIG_PATH%
echo [run_harbor_proxy_local] Harbor API key length: %HARBOR_API_KEY_LEN%
echo [run_harbor_proxy_local] Listening on: %DEX_PROXY_BASE% (port %PORT%)

echo.
python -m dex_proxy.main -s -c "%CONFIG_PATH%" -n harbor %*
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
