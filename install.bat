@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === OTK Nakladnoy — kutubxonalarni o'rnatish (bir marta) ===
python -m pip install -r requirements.txt
echo.
echo Tayyor! Endi .env faylni to'ldiring va start.bat ni ishga tushiring.
pause
