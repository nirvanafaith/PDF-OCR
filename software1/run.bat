@echo off
chcp 65001 >nul
title software1 - Draw Box + OCR

cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\E-VR\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [Error] Python not found: %PYTHON_EXE%
    echo Please install Python 3.12 or edit PYTHON_EXE in this bat file.
    pause
    exit /b 1
)

"%PYTHON_EXE%" main.py

if %errorlevel% neq 0 (
    echo.
    echo [Exited with error code: %errorlevel%]
    pause
)
