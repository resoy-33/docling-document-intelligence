@echo off
REM Watch-folder: start run_api.bat first, then drop files in automation\inbox\.
REM Usage: run_watch.bat "What is the total?"
cd /d "%~dp0"
call ".venv\Scripts\activate.bat" || (echo Run setup.bat first. & pause & exit /b 1)
python automation\watch_folder.py %*
pause
