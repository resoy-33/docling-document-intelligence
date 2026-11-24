@echo off
REM Usage:  run_api.bat          API on real Docling output (output\)
REM         run_api.bat demo     API on the hand-written demo data (no Docling needed)
cd /d "%~dp0"
call ".venv\Scripts\activate.bat" || (echo Run setup.bat first. & pause & exit /b 1)
if /i "%1"=="demo" (set "DOCLING_OUTPUT_DIR=demo\docs") else (if "%DOCLING_OUTPUT_DIR%"=="" set "DOCLING_OUTPUT_DIR=output")
echo Output folder: %DOCLING_OUTPUT_DIR%   Swagger: http://127.0.0.1:8000/docs
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
pause
