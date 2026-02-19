@echo off
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip install -q .

REM Start WhatsApp bridge in background if available
set BRIDGE_DIR=C:\Users\steph\source\repos\whatsapp-mcp\whatsapp-bridge
set BRIDGE_STARTED=0
if exist "%BRIDGE_DIR%\whatsapp-bridge.exe" (
    echo Starting WhatsApp bridge...
    start /B /D "%BRIDGE_DIR%" "" whatsapp-bridge.exe >nul 2>&1
    timeout /t 3 /nobreak >nul
    set BRIDGE_STARTED=1
    echo WhatsApp bridge started.
)

.venv\Scripts\python -m micro_x_agent_loop

REM Clean up bridge on exit
if "%BRIDGE_STARTED%"=="1" (
    echo Stopping WhatsApp bridge...
    taskkill /IM whatsapp-bridge.exe /F >nul 2>&1
)
