@echo off
title OMR GRADING SYSTEM 2025 - DEBUG RUNNER
cd /d "%~dp0"

echo ===================================================
echo   DANG KIEM TRA MOI TRUONG VA KHOI CHAY UNG DUNG...
echo ===================================================

:: 1. Kich hoat moi truong ao
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [CANH BAO] Khong tim thay thu muc .venv!
)

:: 2. Chay ung dung
if exist run_desktop.py (
    python run_desktop.py
) else if exist main_desktop.py (
    python main_desktop.py
) else (
    python -m uvicorn app:app --host 127.0.0.1 --port 8000
)

:: 3. GIU NGUYEN CUA SO NEU CO LOI
echo.
echo ===================================================
echo TIEN TRINH DA DUNG (XEM THONG BAO LOI PHIA TREN).
echo ===================================================
pause