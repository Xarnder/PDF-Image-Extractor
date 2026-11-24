@echo off
setlocal
title PDF Image Extractor
pushd "%~dp0"
if errorlevel 1 exit /b 1

if exist ".venv-windows\Scripts\python.exe" (
    ".venv-windows\Scripts\python.exe" "scripts\windows_launcher.py" %*
    goto finished
)

py -3.12 -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
if not errorlevel 1 (
    py -3.12 "scripts\windows_launcher.py" %*
    goto finished
)

python -c "import sys; assert sys.version_info[:2] == (3, 12)" >nul 2>&1
if not errorlevel 1 (
    python "scripts\windows_launcher.py" %*
    goto finished
)

echo Python 3.12 is required. Install it from https://www.python.org/downloads/windows/
echo Enable the Python launcher or Add Python to PATH, then double-click this file again.
popd
pause
exit /b 1

:finished
set "PDF_EXTRACTOR_EXIT=%errorlevel%"
popd
if not "%PDF_EXTRACTOR_EXIT%"=="0" (
    echo.
    echo PDF Image Extractor could not start or exited with an error.
    echo Read the message above before closing this window.
    pause
)
exit /b %PDF_EXTRACTOR_EXIT%
