@echo off
echo.
echo   Configuring Claude Desktop for Rhino AI Bridge...
echo.

:: Get the directory of this script
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%

:: Write config (won't overwrite other MCP servers — use merge)
powershell -ExecutionPolicy Bypass -Command ^
  "$configPath = \"$env:APPDATA\Claude\claude_desktop_config.json\"; " ^
  "$dir = '%SCRIPT_DIR%' -replace '\\', '\\\\'; " ^
  "$server = @{command='uv'; args=@('--directory', '%SCRIPT_DIR%', 'run', 'rhino-architect')}; " ^
  "if (Test-Path $configPath) { try { $c = Get-Content $configPath -Raw | ConvertFrom-Json } catch { $c = [PSCustomObject]@{} } } else { New-Item -Path (Split-Path $configPath) -ItemType Directory -Force | Out-Null; $c = [PSCustomObject]@{} }; " ^
  "if (-not $c.mcpServers) { $c | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([PSCustomObject]@{}) }; " ^
  "$c.mcpServers | Add-Member -NotePropertyName 'rhino-architect' -NotePropertyValue $server -Force; " ^
  "$c | ConvertTo-Json -Depth 10 | Out-File $configPath -Encoding ASCII; " ^
  "Write-Host '  Done — restart Claude Desktop'"

echo.
pause
