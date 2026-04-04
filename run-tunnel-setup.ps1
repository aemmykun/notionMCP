# Wrapper script to run tunnel setup with proper PATH
# This ensures cloudflared is available before running the main script

Write-Host "Preparing environment..." -ForegroundColor Cyan

# Preserve current session PATH, then append machine and user PATH values.
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$env:Path;$machinePath;$userPath"

# Verify cloudflared is available
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared was not found in PATH." -ForegroundColor Red
    Write-Host "Restart PowerShell and try again." -ForegroundColor Yellow
    exit 1
}

Write-Host "Environment ready" -ForegroundColor Green
Write-Host ""

# Resolve and run the main setup script relative to this wrapper.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$setupScriptPath = Join-Path $scriptDir "setup-tunnel.ps1"

try {
    & $setupScriptPath
    if ($null -ne $LASTEXITCODE) {
        exit $LASTEXITCODE
    }

    if ($?) {
        exit 0
    }

    exit 1
}
catch [System.Management.Automation.PSSecurityException] {
    Write-Host "Script execution is blocked by PowerShell execution policy." -ForegroundColor Red
    Write-Host "Try running for this session only: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass" -ForegroundColor Yellow
    exit 1
}
