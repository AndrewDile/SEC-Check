@echo off
rem Start the SEC-Check Web App (and the mock Core API). Extra flags pass through, e.g.  run.bat --core-url http://host:port
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
) else (
  python run.py %*
)
