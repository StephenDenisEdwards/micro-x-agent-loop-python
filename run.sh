#!/usr/bin/env bash
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    echo "Installing dependencies..."
    .venv/bin/pip install -q .
fi
.venv/bin/python -m micro_x_agent_loop
