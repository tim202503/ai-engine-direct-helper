@echo off
REM start.bat — one-click launcher for Genie Notes on Windows on Snapdragon.
REM NOTE: start GenieAPIService (port 8910) in a separate window first.
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

echo Starting Genie Notes (make sure GenieAPIService is running on port 8910)...
python main.py %*

endlocal
pause
