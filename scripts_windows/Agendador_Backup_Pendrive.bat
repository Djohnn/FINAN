@echo off
set "ROOT=%~dp0.."
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\manage.py" realizar_backup --if-due
exit /b %ERRORLEVEL%
