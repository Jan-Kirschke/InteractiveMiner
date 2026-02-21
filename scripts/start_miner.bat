@echo off
title Infinite Miner Ultimate
echo ==========================================
echo   INFINITE MINER ULTIMATE
echo ==========================================
echo.
echo Starting the miner game...
echo.
cd /d "%~dp0.."
venv\Scripts\python miner\main.py
pause
