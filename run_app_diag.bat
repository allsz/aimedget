@echo off
cd /d "%~dp0"
rem Modo diagnostico da deteccao de midia: registra o que cada site/app envia ao Windows em
rem %LOCALAPPDATA%\Aimedget\media_diagnostic.jsonl (nao muda o comportamento do app).
set AIMEDGET_MEDIA_DIAG=1
echo Iniciando Aimedget Suite (diagnostico de midia ligado)...
python -m app.main
pause
