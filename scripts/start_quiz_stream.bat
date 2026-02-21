@echo off
title The Lifelong Quiz - YouTube Stream Mode
echo ==========================================
echo   THE LIFELONG QUIZ - YouTube Stream Mode
echo ==========================================
echo.
echo Before running, make sure you have set these in quiz\config.py:
echo   STREAM_ENABLED = True
echo   YOUTUBE_STREAM_KEY = "your-stream-key-here"
echo.
echo Press F2 during gameplay to toggle streaming on/off.
echo Press ESC to quit.
echo.
cd /d "%~dp0.."
venv\Scripts\python -m quiz.game
pause
