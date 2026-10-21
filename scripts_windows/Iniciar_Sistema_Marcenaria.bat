@echo off
title Sistema de Gestao - Marcenaria
echo Iniciando o Sistema da Marcenaria...
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

:: Inicia o servidor Django e abre o navegador em modo Aplicativo
start "" http://127.0.0.1:8000
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\manage.py" runserver 127.0.0.1:8000 --insecure
