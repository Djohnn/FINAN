@echo off
cd /d "%~dp0"
echo Executando backup diario no pendrive...
python manage.py realizar_backup
