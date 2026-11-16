@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ---- inicia o servidor se a porta 8090 ainda nao estiver em uso ----
set "PY=python"
where py >nul 2>nul && set "PY=py -3"

netstat -ano | findstr /R /C:":8090 .*LISTENING" >nul
if errorlevel 1 (
  echo Iniciando o servidor do painel...
  start "Painel CONASEMS - servidor" /min %PY% servidor.py --tv
  timeout /t 5 /nobreak >nul
) else (
  echo Servidor ja em execucao na porta 8090.
)

rem ---- localiza Chrome ou Edge para abrir em modo kiosk ----
set "NAV="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "NAV=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined NAV if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "NAV=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined NAV if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "NAV=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if not defined NAV if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "NAV=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined NAV if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "NAV=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if defined NAV (
  start "" "%NAV%" --kiosk "http://localhost:8090/" --incognito --disable-pinch --overscroll-history-navigation=0
) else (
  echo Navegador nao encontrado. Abrindo no navegador padrao...
  start "" "http://localhost:8090/"
)

endlocal
