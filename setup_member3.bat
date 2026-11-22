@echo off
REM Member 3 light setup: installs the API/QA dependencies only (no Docling download),
REM generates the hand-written demo output, and runs the full test suite.
cd /d "%~dp0"
echo === Creating/updating virtual environment (.venv) ===
py -3.12 -m venv .venv || python -m venv .venv
if not exist ".venv\Scripts\activate.bat" (
  echo ERROR: could not create .venv. Check that Python 3.12 is installed: python --version
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
echo === Installing Member 3 requirements (light) ===
python -m pip install --upgrade pip
pip install -r requirements-api.txt
echo === Generating demo/docs (hand-written, not Docling output) ===
python demo\make_demo.py
echo === Running the full test suite ===
python -m pytest -q
echo.
echo Done. Next: double-click run_demo_api.bat, then open http://127.0.0.1:8000/docs
pause
