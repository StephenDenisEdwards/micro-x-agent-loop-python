#!/usr/bin/env bash
set -e

# -- Config: create config.json if missing --
if [ ! -f config.json ]; then
    echo "No config.json found — creating default (config-base.json)"
    echo '{"ConfigFile": "config-base.json"}' > config.json
fi

# -- Python: create venv and install --
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi
.venv/bin/pip install -q .

# -- MCP servers: build if not already built --
if [ ! -f mcp_servers/ts/packages/filesystem/dist/index.js ]; then
    echo "Building MCP servers..."
    if ! command -v node >/dev/null 2>&1; then
        echo "WARNING: Node.js not found — MCP tools will not be available."
        echo "Install Node.js 18+: https://nodejs.org/en/download"
    else
        (cd mcp_servers/ts && npm install && npm run build)
        echo "MCP servers built."
    fi
fi

# -- Run --
.venv/bin/python -m micro_x_agent_loop "$@"
