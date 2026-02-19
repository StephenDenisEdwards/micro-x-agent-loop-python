@echo off
if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv .venv
)
.venv\Scripts\pip install -q .

REM Start WhatsApp bridge in background if available
set BRIDGE_EXE=C:\Users\steph\source\repos\whatsapp-mcp\whatsapp-bridge\whatsapp-bridge.exe
set BRIDGE_STARTED=0
if exist "%BRIDGE_EXE%" (
    echo Starting WhatsApp bridge...
    start /B "" "%BRIDGE_EXE%" >nul 2>&1
    timeout /t 2 /nobreak >nul
    set BRIDGE_STARTED=1
    echo WhatsApp bridge started.
)

.venv\Scripts\python -m micro_x_agent_loop

REM Clean up bridge on exit
if "%BRIDGE_STARTED%"=="1" (
    echo Stopping WhatsApp bridge...
    taskkill /IM whatsapp-bridge.exe /F >nul 2>&1
)
