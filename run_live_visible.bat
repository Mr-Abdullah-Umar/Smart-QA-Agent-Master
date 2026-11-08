@echo off
title AI QA Testing Harness - Live Visible Google Chrome Execution
cd /d "%~dp0"
echo ======================================================================
echo  AI QA TESTING HARNESS -- LIVE GOOGLE CHROME EXECUTION
echo  Target: https://the-internet.herokuapp.com/login
echo  Credentials: tomsmith / SuperSecretPassword!
echo ======================================================================
echo.
engine\.venv\Scripts\python.exe engine\run_live_workflow.py
echo.
pause
