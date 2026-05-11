@echo off
echo.
echo   ====================================
echo    Building Rhino AI Bridge v4.5
echo   ====================================
echo.
where dotnet >nul 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: .NET 8 SDK not found
    echo   Download: https://dotnet.microsoft.com/download/dotnet/8.0
    pause & exit /b 1
)
echo   [1/3] Restoring packages...
dotnet restore
if %errorlevel% neq 0 ( echo   FAILED & pause & exit /b 1 )
echo   [2/3] Building...
dotnet build --configuration Release
if %errorlevel% neq 0 ( echo   FAILED & pause & exit /b 1 )
echo   [3/3] Installing...
set PD=%APPDATA%\McNeel\Rhinoceros\8.0\Plug-ins\RhinoAIBridge
set BD=bin\Release\net8.0
if not exist "%PD%" mkdir "%PD%"
copy /Y "%BD%\RhinoAIBridge.rhp"              "%PD%\" >nul
copy /Y "%BD%\RhinoAIBridge.deps.json"        "%PD%\" >nul
copy /Y "%BD%\RhinoAIBridge.runtimeconfig.json" "%PD%\" >nul
copy /Y "%BD%\Newtonsoft.Json.dll"            "%PD%\" >nul
copy /Y "%BD%\System.Drawing.Common.dll"      "%PD%\" >nul
if exist "%BD%\Microsoft.Win32.SystemEvents.dll" (
    copy /Y "%BD%\Microsoft.Win32.SystemEvents.dll" "%PD%\" >nul
)
echo.
echo   ====================================
echo    BUILD SUCCESSFUL
echo   ====================================
echo.
echo   Plugin: %PD%\RhinoAIBridge.rhp
echo.
echo   FIRST TIME: Rhino 8 ^> PlugInManager ^> Install ^> browse to .rhp
echo   AFTER THAT: Auto-loads. Type "AIBridge" to restart server.
echo   LOGS: %APPDATA%\AIBridge\logs\
echo.
pause
