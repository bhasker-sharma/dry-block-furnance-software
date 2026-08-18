@echo off
REM ============================================================================
REM  Build DryBlockCalibrator.exe - a single standalone Windows executable.
REM
REM  Bundles the Python interpreter and every dependency (PyQt5 + its Qt5
REM  DLLs, pyserial, reportlab, Pillow) into one .exe via PyInstaller, so the
REM  target PC needs nothing pre-installed - no Python, no separate Qt
REM  runtime, no pip packages, no third-party drivers.
REM
REM  Output: dist\DryBlockCalibrator.exe
REM ============================================================================

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found at venv\Scripts\python.exe
    echo         Run this first:  python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "asset\logo.ico" (
    echo [ERROR] Icon not found at asset\logo.ico
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo === Checking PyInstaller ===
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found - installing...
    pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller already installed.
)

echo.
echo === Cleaning previous build output ===
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "DryBlockCalibrator.spec" del /q "DryBlockCalibrator.spec"

if exist "dist\DryBlockCalibrator.exe" (
    echo [ERROR] dist\DryBlockCalibrator.exe is still in use - close any
    echo         running copy of the app ^(check the taskbar / Task Manager^)
    echo         and run this script again.
    pause
    exit /b 1
)

echo.
echo === Building DryBlockCalibrator.exe ===
pyinstaller ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --name "DryBlockCalibrator" ^
    --icon "asset\logo.ico" ^
    --add-data "asset;asset" ^
    --collect-all reportlab ^
    --hidden-import serial.tools.list_ports_windows ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed - see the PyInstaller output above.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo  Build complete:  dist\DryBlockCalibrator.exe
echo ============================================================================
pause
