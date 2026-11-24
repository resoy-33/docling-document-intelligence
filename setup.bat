@echo off
REM Usage:  setup.bat          light install (API, Q&A, harness, inspector, tests: no Docling models)
REM         setup.bat full     full install with real Docling (about 5 GB on first conversion)
cd /d "%~dp0"
py -3.12 -m venv .venv || python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if /i "%1"=="full" (pip install -r requirements.txt) else (pip install -r requirements-api.txt)
python demo\make_demo.py
python -m pytest -q
pause
