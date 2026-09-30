@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%main.py" %*
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 "%SCRIPT_DIR%main.py" %*
    ) else (
        python "%SCRIPT_DIR%main.py" %*
    )
)
exit /b %errorlevel%
