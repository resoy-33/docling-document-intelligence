@echo off
cd /d "%~dp0"
call ".venv\Scripts\activate.bat" || (echo Run setup.bat first. & pause & exit /b 1)
python demo\make_demo.py
python -m pytest -q
pause
