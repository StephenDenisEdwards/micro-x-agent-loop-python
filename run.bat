@echo off
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    echo Installing dependencies...
    .venv\Scripts\pip install -q .
)
.venv\Scripts\python -m micro_x_agent_loop
