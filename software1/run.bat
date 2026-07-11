@echo off
chcp 65001 >nul
title software1 - Draw Box + OCR

cd /d "%~dp0"

set "PYTHON_EXE=python"
where "%PYTHON_EXE%" >nul 2>nul
if errorlevel 1 (
    echo [Error] Python not found in PATH
    echo Please install Python 3.12 or add it to PATH.
    pause
    exit /b 1
)

"%PYTHON_EXE%" main.py

if %errorlevel% neq 0 (
    echo.
    echo [Exited with error code: %errorlevel%]
    pause
)
