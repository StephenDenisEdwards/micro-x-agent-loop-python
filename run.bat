@echo off

REM Config: create config.json if missing
if not exist config.json (
    echo No config.json found - creating default ^(config-starter.json^)
    echo ^{"ConfigFile": "config-starter.json"^} > config.json
)

REM Python: create venv and install
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip install -q .

REM MCP servers: build if not already built
if not exist mcp_servers\ts\packages\filesystem\dist\index.js (
    where node >nul 2>&1 || (
        echo WARNING: Node.js not found - MCP tools will not be available.
        echo Install Node.js 18+: https://nodejs.org/en/download
        goto :mcp_done
    )
    echo Building MCP servers...
    pushd mcp_servers\ts
    call npm install
    call npm run build
    popd
    echo MCP servers built.
)
:mcp_done

REM Run the agent
.venv\Scripts\python.exe -m micro_x_agent_loop %*
