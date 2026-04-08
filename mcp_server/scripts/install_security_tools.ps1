#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Install security scanning tools for MCP server

.DESCRIPTION
    Installs pip-audit, bandit, and safety for security scanning.
    Run this before running security_scan.py

.EXAMPLE
    .\install_security_tools.ps1
#>

Write-Host "Installing security scanning tools..." -ForegroundColor Cyan

# Activate virtual environment if it exists
if (Test-Path venv\Scripts\Activate.ps1) {
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    & .\venv\Scripts\Activate.ps1
}

# Install tools
Write-Host "`nInstalling pip-audit..." -ForegroundColor Yellow
pip install pip-audit

Write-Host "`nInstalling bandit..." -ForegroundColor Yellow
pip install bandit

Write-Host "`nInstalling safety..." -ForegroundColor Yellow
pip install safety

Write-Host "`n✅ Security tools installed successfully!" -ForegroundColor Green
Write-Host "`nYou can now run:" -ForegroundColor Cyan
Write-Host "  python security_scan.py" -ForegroundColor White
Write-Host "  python security_scan.py --fail-on-high" -ForegroundColor White
