@echo off
echo.
echo  Writing Bot - Personal Style AI
echo  ================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.10+ from python.org
    pause & exit /b 1
)

:: Check for API key
if "%ANTHROPIC_API_KEY%"=="" (
    echo  WARNING: ANTHROPIC_API_KEY is not set.
    echo  Set it with:  set ANTHROPIC_API_KEY=sk-ant-...
    echo.
)

:: Install deps if needed
if not exist ".venv" (
    echo  Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo  Installing / checking dependencies...
pip install -q -r requirements.txt

echo.
echo  Starting server at http://localhost:5000
echo  Press Ctrl+C to stop.
echo.

python app.py
