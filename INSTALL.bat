@echo off
setlocal enabledelayedexpansion

:: ============================================================
::   RhinoAIBridge -- One-Click Installer
::   by tanishqb  |  https://github.com/tanishqbhattad/rhino-mcp
::   Version 4.5  |  Supports Claude Desktop, ChatGPT, Ollama
::   Pre-built plugin -- .NET SDK NOT required.
:: ============================================================

title RhinoAIBridge Installer by tanishqb

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "DIST_DIR=%ROOT%\dist\plugin"
set "SERVER_DIR=%ROOT%\server"
set "SCRIPTS_DIR=%ROOT%\scripts"
set "RHINO_PLUGIN_DIR=%APPDATA%\McNeel\Rhinoceros\8.0\Plug-ins\RhinoAIBridge"

echo.
echo  ============================================================
echo    RhinoAIBridge Installer  ^|  by tanishqb
echo    The most powerful AI Bridge for Rhino 3D
echo    https://github.com/tanishqbhattad/rhino-mcp
echo  ============================================================
echo.
echo  This installer will:
echo    [1] Copy pre-built Rhino plugin  ^(no .NET SDK required^)
echo    [2] Install Python MCP server
echo    [3] Configure Claude Desktop  ^(if installed^)
echo.
echo  Press any key to begin, or Ctrl+C to cancel.
pause >nul
echo.

:: -- [1] Install pre-built Rhino plugin ------------------------------------------
echo  [1/3] Installing Rhino plugin...

if not exist "%DIST_DIR%\RhinoAIBridge.rhp" goto :err_no_rhp
if not exist "%RHINO_PLUGIN_DIR%" mkdir "%RHINO_PLUGIN_DIR%"
copy /Y "%DIST_DIR%\RhinoAIBridge.rhp"                    "%RHINO_PLUGIN_DIR%\" >nul
copy /Y "%DIST_DIR%\Newtonsoft.Json.dll"                  "%RHINO_PLUGIN_DIR%\" >nul
if exist "%DIST_DIR%\System.Drawing.Common.dll"           copy /Y "%DIST_DIR%\System.Drawing.Common.dll"        "%RHINO_PLUGIN_DIR%\" >nul
if exist "%DIST_DIR%\Microsoft.Win32.SystemEvents.dll"    copy /Y "%DIST_DIR%\Microsoft.Win32.SystemEvents.dll" "%RHINO_PLUGIN_DIR%\" >nul
echo  OK  ^(plugin installed to %RHINO_PLUGIN_DIR%^)
goto :step2

:err_no_rhp
echo.
echo  ERROR: Pre-built plugin not found at:
echo         %DIST_DIR%\RhinoAIBridge.rhp
echo.
echo  Make sure you extracted the full zip before running this installer.
echo.
pause
exit /b 1

:: -- [2] Install / verify uv ------------------------------------------------------
:step2
echo  [2/3] Checking uv ...
where uv >nul 2>&1
if not errorlevel 1 goto :uv_ok

echo  uv not found -- installing now...
powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if errorlevel 1 goto :err_uv_install

set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>&1
if errorlevel 1 goto :err_uv_path

echo  uv installed successfully.
goto :uv_ok

:err_uv_install
echo.
echo  ERROR: Could not auto-install uv.
echo  Install manually: https://docs.astral.sh/uv/getting-started/installation/
echo  Then run INSTALL.bat again.
echo.
pause
exit /b 1

:err_uv_path
echo.
echo  uv installed but PATH not refreshed yet.
echo  Please close this window and run INSTALL.bat again.
echo.
pause
exit /b 1

:uv_ok
echo  OK

:: -- [3] Install Python MCP server dependencies -----------------------------------
echo  [3/3] Installing Python server dependencies...
cd /d "%SERVER_DIR%"
uv sync
if errorlevel 1 goto :err_uv_sync
echo  OK  ^(MCP server ready^)
goto :config

:err_uv_sync
echo.
echo  ERROR: uv sync failed. See errors above.
echo  Try manually:  cd "%SERVER_DIR%" ^&^& uv sync
echo.
pause
exit /b 1

:: -- Configure Claude Desktop (via Python -- bulletproof JSON) --------------------
:config
echo.
echo  Configuring Claude Desktop...
cd /d "%SERVER_DIR%"
uv run python "%SCRIPTS_DIR%\patch_claude_config.py" "%SERVER_DIR%"
echo.

:: -- Done -------------------------------------------------------------------------
echo  ============================================================
echo    INSTALLATION COMPLETE  ^|  RhinoAIBridge by tanishqb
echo  ============================================================
echo.
echo  NEXT STEPS:
echo.
echo  1. Open Rhino 8
echo  2. Run command:  PlugInManager
echo     Click Install and browse to:
echo     %RHINO_PLUGIN_DIR%\RhinoAIBridge.rhp
echo     ^(Skip on future installs -- it auto-loads^)
echo.
echo  3. In Rhino command line type:  AIBridge
echo     ^(Do this every time you open Rhino^)
echo.
echo  --- Claude Desktop ------------------------------------
echo  4. Restart Claude Desktop
echo  5. Ask Claude:  ping Rhino   to confirm connection
echo.
echo  --- ChatGPT or Ollama ^(optional^) --------------------
echo     cd "%SERVER_DIR%"
echo     uv run python chat.py --provider ollama --model qwen2.5-coder:7b
echo     uv run python chat.py --provider openai
echo     ^(set OPENAI_API_KEY env variable first for OpenAI^)
echo.
echo  --- Docs and Help ------------------------------------
echo     https://github.com/tanishqbhattad/rhino-mcp
echo.
echo  ============================================================
echo.
pause
