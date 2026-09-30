@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" gui.py
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 gui.py
    ) else (
        python gui.py
    )
)
if errorlevel 1 pause
