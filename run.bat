@echo off

REM Config: create config.json if missing
if not exist config.json (
    echo No config.json found - creating default ^(config-base.json^)
    echo ^{"ConfigFile": "config-base.json"^} > config.json
)

REM Python: create venv and install
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip install -q .

REM MCP servers: install deps if missing, always rebuild so source edits take effect
where node >nul 2>&1 || (
    echo WARNING: Node.js not found - MCP tools will not be available.
    echo Install Node.js 18+: https://nodejs.org/en/download
    goto :mcp_done
)
pushd mcp_servers\ts
if not exist node_modules (
    echo Installing MCP server dependencies...
    call npm install
)
echo Building MCP servers...
call npm run build
popd
:mcp_done

REM Run the agent
.venv\Scripts\python.exe -m micro_x_agent_loop %*
