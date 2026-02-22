@echo off
title The Lifelong Quiz - YouTube Live
echo ==========================================
echo   THE LIFELONG QUIZ - YouTube Live Mode
echo ==========================================
echo.
echo Options:
echo   1. Enter a specific Video ID
echo   2. Auto-detect from configured channels (uses quiz/config.py CHANNEL_IDS)
echo.
set /p CHOICE="Enter Video ID (or press Enter for auto-detect): "
cd /d "%~dp0.."
if "%CHOICE%"=="" (
    echo.
    echo Auto-detecting livestream from configured channels...
    echo Press ESC to quit, F1 to skip phase.
    echo.
    venv\Scripts\python -m quiz.game
) else (
    echo.
    echo Connecting to video: %CHOICE%
    echo Press ESC to quit, F1 to skip phase.
    echo.
    venv\Scripts\python -m quiz.game %CHOICE%
)
pause
