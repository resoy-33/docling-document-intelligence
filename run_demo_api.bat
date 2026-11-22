@echo off
REM Starts the API on the hand-written demo output. No Docling needed.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo ERROR: run setup_member3.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
if not exist "demo\docs\sales_2026\summary.json" (
  echo Generating demo\docs...
  python demo\make_demo.py
)
set "DOCLING_OUTPUT_DIR=demo\docs"
echo.
echo API:    http://127.0.0.1:8000
echo Swagger: http://127.0.0.1:8000/docs
echo Demo question:
echo   curl.exe -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"What were Laptops sales in Q1?\",\"doc_id\":\"sales_2026\"}"
echo.
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
pause
