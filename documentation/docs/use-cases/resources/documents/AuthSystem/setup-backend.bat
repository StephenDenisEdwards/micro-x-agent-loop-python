@echo off
echo Setting up .NET Backend...
cd AuthSystem.Api

echo.
echo Restoring NuGet packages...
dotnet restore

echo.
echo Building project...
dotnet build

echo.
echo Creating database...
dotnet ef database update

echo.
echo Setup complete! Run 'start-backend.bat' to start the API server.
pause
