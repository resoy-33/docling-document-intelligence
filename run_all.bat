@echo off
REM Docling engine -> harness gate -> pdfplumber baseline -> harness on the baseline -> comparison report.
cd /d "%~dp0"
call ".venv\Scripts\activate.bat" || (echo Run setup.bat full first. & pause & exit /b 1)
echo === 1/5 Docling engine on samples\ (first run downloads models) ===
python -m engine.convert samples --out output
echo === 2/5 Harness on Docling output ===
python -m harness.validate output
echo === 3/5 pdfplumber baseline ===
python -m baseline.compare_pdfplumber samples --out output_baseline
echo === 4/5 Harness on baseline output ===
python -m harness.validate output_baseline
echo === 5/5 Comparison report ===
python -m baseline.compare_report
echo Results: output\  output_baseline\  comparison_report.md
pause
