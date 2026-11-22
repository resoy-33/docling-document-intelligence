@echo off
REM Starts the API on the real engine output folder (output\). Run Member 1's engine first:
REM   python -m engine.convert samples --out output
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo ERROR: run setup_member3.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
if "%DOCLING_OUTPUT_DIR%"=="" set "DOCLING_OUTPUT_DIR=output"
if not exist "%DOCLING_OUTPUT_DIR%" (
  echo WARNING: %DOCLING_OUTPUT_DIR% does not exist yet.
  echo Run: python -m engine.convert samples --out output
)
echo API output folder: %DOCLING_OUTPUT_DIR%
echo Swagger: http://127.0.0.1:8000/docs
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
pause
