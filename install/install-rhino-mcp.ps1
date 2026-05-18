#Requires -Version 5.1
<#
.SYNOPSIS
    RhinoAIBridge v4.7 one-click installer.
    Detects Claude Desktop, Claude Code, and Codex; installs the .rhp into
    Rhino 8, syncs the Python venv, and writes the MCP config for every
    tool found.

.DESCRIPTION
    Run from the repo root or install/ subfolder:
        powershell -ExecutionPolicy Bypass -File install\install-rhino-mcp.ps1

    The script is idempotent — safe to run again after updates.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Resolve repo root ────────────────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = if ((Split-Path -Leaf $scriptDir) -eq "install") { Split-Path -Parent $scriptDir } else { $scriptDir }
$serverDir = Join-Path $repoRoot "server"
$rhpSrc    = Join-Path $repoRoot "plugin\bin\Release\net7.0\RhinoAIBridge.rhp"

function Banner($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function OK($msg)     { Write-Host "  [OK] $msg"    -ForegroundColor Green }
function WARN($msg)   { Write-Host "  [!]  $msg"    -ForegroundColor Yellow }
function ERR($msg)    { Write-Host "  [X]  $msg"    -ForegroundColor Red }
function INFO($msg)   { Write-Host "  ... $msg"     -ForegroundColor Gray }

# ── 1. Preflight ─────────────────────────────────────────────────────────────
Banner "Preflight checks"

if (-not (Test-Path $rhpSrc)) {
    ERR "RhinoAIBridge.rhp not found at: $rhpSrc"
    ERR "Build the C# plugin first: cd plugin && dotnet build -c Release"
    exit 1
}
OK "Plugin binary: $rhpSrc ($([int]((Get-Item $rhpSrc).Length/1024)) KB)"

$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvPath) {
    ERR "'uv' not found in PATH. Install from https://astral.sh/uv"
    exit 1
}
OK "uv: $($uvPath.Source)"

# Ensure Rhino is closed before installing
$rhinoProcs = Get-Process -Name "Rhino" -ErrorAction SilentlyContinue
if ($rhinoProcs) {
    WARN "Rhino is running (PID $($rhinoProcs.Id)). The .rhp will be installed but won't load until restart."
}

# ── 2. Install .rhp into Rhino 8 ─────────────────────────────────────────────
Banner "Installing .rhp into Rhino 8"

$rhinoPluginDir = Join-Path $env:APPDATA "McNeel\Rhinoceros\8.0\Plug-ins\RhinoAIBridge"
if (-not (Test-Path $rhinoPluginDir)) {
    New-Item -ItemType Directory -Path $rhinoPluginDir -Force | Out-Null
}
$rhpDst = Join-Path $rhinoPluginDir "RhinoAIBridge.rhp"
Copy-Item $rhpSrc $rhpDst -Force
OK "Installed: $rhpDst"

# ── 3. Sync Python venv ───────────────────────────────────────────────────────
Banner "Syncing Python venv (uv sync --frozen)"
Push-Location $serverDir
try {
    & uv sync --frozen 2>&1 | ForEach-Object { INFO $_ }
    OK "venv synced at $serverDir\.venv"
} catch {
    WARN "uv sync warning: $_"
} finally {
    Pop-Location
}

# ── 4. Build MCP server entry string ─────────────────────────────────────────
$mcpBlock = [ordered]@{
    command = "uv"
    args    = @("--directory", $serverDir, "run", "--frozen", "rhino-architect")
    env     = [ordered]@{
        RHINO_HOST      = "127.0.0.1"
        RHINO_PORT      = "9544"
        RHINO_SAFE_MODE = "0"
    }
}

# ── 5. Claude Desktop ─────────────────────────────────────────────────────────
Banner "Claude Desktop"

$cdConfig = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
$cdFound  = Test-Path $cdConfig

if ($cdFound) {
    INFO "Config found: $cdConfig"
    # Stop Claude Desktop before writing
    $cdProcs = Get-Process -Name "Claude" -ErrorAction SilentlyContinue
    if ($cdProcs) {
        INFO "Stopping Claude Desktop (PID $($cdProcs.Id)) ..."
        $cdProcs | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
    try {
        $existing = Get-Content $cdConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        WARN "Could not parse existing config — creating fresh."
        $existing = [pscustomobject]@{}
    }
    # Ensure mcpServers exists
    if (-not ($existing.PSObject.Properties.Name -contains "mcpServers")) {
        $existing | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([pscustomobject]@{})
    }
    $existing.mcpServers | Add-Member -NotePropertyName "rhino-architect" -NotePropertyValue $mcpBlock -Force
    $existing | ConvertTo-Json -Depth 10 | Set-Content -Path $cdConfig -Encoding UTF8 -NoNewline
    OK "Written to Claude Desktop config"
} else {
    WARN "Claude Desktop config not found (app not installed or never launched). Skipping."
}

# ── 6. Claude Code (.mcp.json in HOME) ────────────────────────────────────────
Banner "Claude Code"

$ccExe   = Get-Command "claude" -ErrorAction SilentlyContinue
$ccFound = $null -ne $ccExe

if ($ccFound) {
    INFO "claude CLI: $($ccExe.Source)"
    $ccConfig = Join-Path $env:USERPROFILE ".mcp.json"
    if (Test-Path $ccConfig) {
        try { $ccObj = Get-Content $ccConfig -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { $ccObj = [pscustomobject]@{} }
    } else {
        $ccObj = [pscustomobject]@{}
    }
    if (-not ($ccObj.PSObject.Properties.Name -contains "mcpServers")) {
        $ccObj | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([pscustomobject]@{})
    }
    $ccObj.mcpServers | Add-Member -NotePropertyName "rhino-architect" -NotePropertyValue $mcpBlock -Force
    $ccObj | ConvertTo-Json -Depth 10 | Set-Content -Path $ccConfig -Encoding UTF8 -NoNewline
    OK "Written to $ccConfig"
} else {
    WARN "'claude' CLI not found — Claude Code not installed. Skipping."
}

# ── 7. Codex ──────────────────────────────────────────────────────────────────
Banner "Codex"

# Codex stores config in %APPDATA%\Codex\codex.mcp.json (or similar)
$codexPaths = @(
    (Join-Path $env:APPDATA "Codex\codex.mcp.json"),
    (Join-Path $env:USERPROFILE ".codex\codex.mcp.json"),
    (Join-Path $env:USERPROFILE "codex.mcp.json")
)
$codexExe   = Get-Command "codex" -ErrorAction SilentlyContinue
$codexFound = $null -ne $codexExe

# Also check if any codex config file already exists
$existingCodexConfig = $codexPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($codexFound -or $existingCodexConfig) {
    $codexConfig = if ($existingCodexConfig) { $existingCodexConfig } else { $codexPaths[0] }
    INFO "Codex config target: $codexConfig"
    $codexDir = Split-Path -Parent $codexConfig
    if (-not (Test-Path $codexDir)) { New-Item -ItemType Directory -Path $codexDir -Force | Out-Null }

    if (Test-Path $codexConfig) {
        try { $codexObj = Get-Content $codexConfig -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { $codexObj = [pscustomobject]@{} }
    } else {
        $codexObj = [pscustomobject]@{}
    }
    if (-not ($codexObj.PSObject.Properties.Name -contains "mcpServers")) {
        $codexObj | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([pscustomobject]@{})
    }
    $codexObj.mcpServers | Add-Member -NotePropertyName "rhino-architect" -NotePropertyValue $mcpBlock -Force
    $codexObj | ConvertTo-Json -Depth 10 | Set-Content -Path $codexConfig -Encoding UTF8 -NoNewline
    OK "Written to $codexConfig"

    # Also write the example file for reference
    $exampleSrc = Join-Path $repoRoot "install\codex.mcp.example.json"
    if (Test-Path $exampleSrc) {
        Copy-Item $exampleSrc $codexDir -Force
        INFO "Example config copied to $codexDir"
    }
} else {
    WARN "Codex not detected (no 'codex' CLI and no existing config). Skipping."
    INFO "To configure manually, see: $repoRoot\install\codex.mcp.example.json"
}

# ── 8. Smoke test ─────────────────────────────────────────────────────────────
Banner "Smoke test — MCP server startup"
Push-Location $serverDir
try {
    INFO "Starting server for 3 seconds ..."
    $job = Start-Job -ScriptBlock {
        param($dir)
        Set-Location $dir
        & uv run --frozen rhino-architect 2>&1
    } -ArgumentList $serverDir

    Start-Sleep -Seconds 3
    $out = Receive-Job $job -ErrorAction SilentlyContinue
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    if ($out -match "error|traceback|ImportError" -and $out -notmatch "Running") {
        WARN "Server output suggests a problem:"
        $out | ForEach-Object { INFO "  $_" }
    } else {
        OK "Server started without errors"
    }
} catch {
    WARN "Smoke test could not be completed: $_"
} finally {
    Pop-Location
}

# ── Summary ───────────────────────────────────────────────────────────────────
Banner "Installation complete"
Write-Host ""
Write-Host "  Plugin:        $rhpDst" -ForegroundColor White
Write-Host "  Server:        $serverDir" -ForegroundColor White
Write-Host "  Claude Desktop: $(if ($cdFound) { 'configured' } else { 'not installed' })" -ForegroundColor White
Write-Host "  Claude Code:    $(if ($ccFound) { 'configured' } else { 'not installed' })" -ForegroundColor White
Write-Host "  Codex:          $(if ($codexFound -or $existingCodexConfig) { 'configured' } else { 'not detected' })" -ForegroundColor White
Write-Host ""
Write-Host "  Next: open Rhino 8 and type 'AIBridge' to start the bridge." -ForegroundColor Cyan
Write-Host "  Run install\rhino-mcp-healthcheck.ps1 to verify the connection." -ForegroundColor Cyan
Write-Host ""
