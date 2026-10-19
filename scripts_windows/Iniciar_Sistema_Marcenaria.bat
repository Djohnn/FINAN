@echo off
title Sistema de Gestao - Marcenaria
echo Iniciando o Sistema da Marcenaria...
cd /d "%~dp0"

:: Inicia o servidor Django e abre o navegador em modo Aplicativo
start "" http://127.0.0.1:8000
python manage.py runserver 127.0.0.1:8000 --insecure
