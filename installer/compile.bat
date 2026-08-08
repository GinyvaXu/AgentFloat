@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================
echo   Claude Code Float - Inno Setup Compile
echo ============================================
echo.

set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

if not exist "%ISCC%" (
    echo [ERROR] Inno Setup not found at: %ISCC%
    echo Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php
    pause
    exit /b 1
)

echo [1/2] Compiling setup.iss...
"%ISCC%" setup.iss
if errorlevel 1 (
    echo [FAIL] Compilation failed!
    pause
    exit /b 1
)

echo.
echo [2/2] Build complete!
echo.
echo Output: ClaudeFloat_Setup_v1.0.exe
echo.

dir "ClaudeFloat_Setup_v1.0.exe" 2>nul

echo.
echo You can now distribute ClaudeFloat_Setup_v1.0.exe
echo.
pause
