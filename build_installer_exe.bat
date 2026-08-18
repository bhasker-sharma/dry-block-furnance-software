@echo off
REM ============================================================================
REM  Build DryBlockCalibrator_Setup.exe - a guided Windows installer that
REM  wraps dist\DryBlockCalibrator.exe with a Start Menu shortcut, optional
REM  Desktop shortcut, and an uninstaller in Add/Remove Programs.
REM
REM  Installs per-user - no admin rights needed. Requires Inno Setup 6 to be
REM  installed on THIS build machine (one-time, not needed on end-user PCs):
REM      https://jrsoftware.org/isdl.php
REM
REM  Requires dist\DryBlockCalibrator.exe to already exist - run
REM  build_exe.bat first.
REM
REM  Output: installer_dist\DryBlockCalibrator_Setup.exe
REM ============================================================================

cd /d "%~dp0"

if not exist "dist\DryBlockCalibrator.exe" (
    echo [ERROR] dist\DryBlockCalibrator.exe not found.
    echo         Run build_exe.bat first to build the app, then run this script.
    pause
    exit /b 1
)

REM Hardcoded rather than %ProgramFiles(x86)% - that variable name's literal
REM parentheses trip up cmd's parser in some contexts, so avoid it outright.
set "ISCC_A=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "ISCC_B=C:\Program Files\Inno Setup 6\ISCC.exe"

set "ISCC="
if exist "%ISCC_A%" set "ISCC=%ISCC_A%"
if exist "%ISCC_B%" set "ISCC=%ISCC_B%"

if "%ISCC%"=="" (
    echo [ERROR] Inno Setup 6 not found on this machine.
    echo         Download and install it from https://jrsoftware.org/isdl.php
    echo         then run this script again. Only needed on the machine that
    echo         builds the installer, not on end-user PCs.
    pause
    exit /b 1
)

echo.
echo === Building installer with Inno Setup ===
"%ISCC%" "installer.iss"

if errorlevel 1 (
    echo.
    echo [ERROR] Installer build failed - see the Inno Setup output above.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo  Installer built:  installer_dist\DryBlockCalibrator_Setup.exe
echo ============================================================================
pause
