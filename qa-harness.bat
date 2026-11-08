@echo off
rem Generic command-line runner for the QA harness. Examples:
rem   qa-harness smoke --url https://your-app --module "Home" --environment staging --approver your-github-name
rem   qa-harness list
rem   qa-harness retest --module "Home" --failed-only --approver your-github-name
rem   qa-harness regression --approver your-github-name
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%engine\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONPATH=%ROOT%engine"
"%PY%" -m qa_engine.cli --workspace "%CD%" %*
exit /b %ERRORLEVEL%
