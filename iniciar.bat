@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

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

start "" "http://localhost:8090/"
endlocal
