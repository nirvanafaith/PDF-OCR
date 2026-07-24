@echo off
chcp 65001 >nul
title software3 - Vector PDF OCR

cd /d "%~dp0"

REM Prefer Python 3.12 (has rapidocr/PyQt6/PyMuPDF/onnxruntime installed)
set "PYTHON_EXE="
if exist "C:\Users\E-VR\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=C:\Users\E-VR\AppData\Local\Programs\Python\Python312\python.exe"
) else (
    set "PYTHON_EXE=python"
    where "%PYTHON_EXE%" >nul 2>nul
    if errorlevel 1 (
        echo [Error] Python not found
        echo Please install Python 3.12 with: PyQt6 PyMuPDF rapidocr onnxruntime-gpu numpy opencv-python scipy
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" main.py

if %errorlevel% neq 0 (
    echo.
    echo [Exited with error code: %errorlevel%]
    pause
)
