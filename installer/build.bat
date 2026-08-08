@echo off
cd /d "%~dp0\.."

echo.
echo ╔══════════════════════════════════════════╗
echo ║   Claude Code Float - Build Installer   ║
echo ╚══════════════════════════════════════════╝
echo.

echo [1/2] PyInstaller compiling...
python build_exe.py
if errorlevel 1 (
    echo [FAIL] Build failed!
    pause
    exit /b 1
)

echo.
echo [2/2] Testing install...
python installer\install.py --quiet

echo.
echo Done! Output: dist\ClaudeFloat.exe
pause
