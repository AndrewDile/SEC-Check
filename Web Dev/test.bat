@echo off
rem Run the automated tests (no server needs to be running).
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m unittest %*
) else (
  python -m unittest %*
)
