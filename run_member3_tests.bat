@echo off
REM Runs the Member 3 tests (and then the whole suite) against the demo output.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo ERROR: run setup_member3.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python demo\make_demo.py
python -m pytest -q tests\test_qa_chunking.py tests\test_qa_answer.py tests\test_api.py
echo.
echo === Full project suite ===
python -m pytest -q
pause
