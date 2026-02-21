@echo off
title The Lifelong Quiz - Fake Chat Mode
echo ==========================================
echo   THE LIFELONG QUIZ - Offline Dev Mode
echo ==========================================
echo.
echo Starting with fake chat bots...
echo Press ESC to quit, F1 to skip phase.
echo.
cd /d "%~dp0.."
venv\Scripts\python -m quiz.game
pause
