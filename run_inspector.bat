@echo off
REM Bounding-box inspector (Streamlit). Needs converted documents in output\ (python -m engine.convert samples --out output).
cd /d "%~dp0"
call ".venv\Scripts\activate.bat" || (echo Run setup.bat first. & pause & exit /b 1)
if "%DOCLING_OUTPUT_DIR%"=="" set "DOCLING_OUTPUT_DIR=output"
python -m streamlit run inspector\app.py
pause
