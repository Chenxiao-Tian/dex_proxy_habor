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
    if /i "!key!"=="DEX_PROXY_BASE" set "DEX_PROXY_BASE=!value!"
  )
)

if not defined DEX_PROXY_BASE set "DEX_PROXY_BASE=http://127.0.0.1:1958"

echo [run_vasquez_local] Using DEX proxy base: %DEX_PROXY_BASE%
echo [run_vasquez_local] Default symbol: ETHUSDT

echo.
python vasquez/examples/run_vasquez_binance.py --base "%DEX_PROXY_BASE%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd >nul
exit /b %EXIT_CODE%
