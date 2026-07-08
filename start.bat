@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === OTK Nakladnoy bot ishga tushmoqda (http://localhost:8080) ===
echo To'xtatish: bu oynani yoping yoki Ctrl+C
python -m uvicorn server:app --host 0.0.0.0 --port 8080
pause
