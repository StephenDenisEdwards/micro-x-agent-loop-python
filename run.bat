@echo off
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip show micro-x-agent-loop >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    .venv\Scripts\pip install -q .
)
.venv\Scripts\python -m micro_x_agent_loop
