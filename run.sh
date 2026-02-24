#!/usr/bin/env bash
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
.venv/bin/pip install -q .
.venv/bin/python -m micro_x_agent_loop
