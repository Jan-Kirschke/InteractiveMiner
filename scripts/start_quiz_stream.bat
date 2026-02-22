@echo off
title The Lifelong Quiz - YouTube Stream Mode
echo ==========================================
echo   THE LIFELONG QUIZ - YouTube Stream Mode
echo ==========================================
echo.
echo This mode streams to YouTube AND reads live chat.
echo.
echo To read chat, enter your stream's Video ID.
echo Find it in YouTube Studio: the part after watch?v= in your stream URL.
echo Example: if URL is youtube.com/watch?v=AbCdEf12345 then enter AbCdEf12345
echo.
echo Or press Enter to auto-detect (may take 30-60s after going live).
echo.
set /p VID_ID="Enter Video ID (or press Enter for auto-detect): "
cd /d "%~dp0.."
if "%VID_ID%"=="" (
    echo.
    echo Auto-detecting livestream from configured channels...
    echo Chat will connect once a live stream is found.
    echo Press F2 to toggle streaming, ESC to quit.
    echo.
    venv\Scripts\python -m quiz.game
) else (
    echo.
    echo Streaming + reading chat from video: %VID_ID%
    echo Press F2 to toggle streaming, ESC to quit.
    echo.
    venv\Scripts\python -m quiz.game %VID_ID%
)
pause
