@echo off
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip install -q .
.venv\Scripts\python -m micro_x_agent_loop
