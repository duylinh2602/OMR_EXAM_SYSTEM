@echo off
chcp 65001 >nul
title ĐÓNG GÓI BỘ CÀI ĐẶT HỆ THỐNG CHẤM THI OMR 2026
echo =======================================================================
echo          BẮT ĐẦU ĐÓNG GÓI BỘ CÀI ĐẶT SETUP_OMR_SYSTEM_2026.EXE
echo =======================================================================
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" package_all.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] CÓ LỖI XẢY RA TRONG QUÁ TRÌNH ĐÓNG GÓI!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [✓] ĐÓNG GÓI HOÀN TẤT!
pause
