# Cloudflare Tunnel Setup Script for Notion MCP
# Production-ready, idempotent tunnel configuration

Write-Host "Cloudflare Tunnel Setup for mcp.tenantsage.org" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Gray
Write-Host ""

Write-Host "Pre-flight checks..." -ForegroundColor Yellow

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Install with: winget install Cloudflare.cloudflared" -ForegroundColor White
    Write-Host "Then restart PowerShell and run this script again." -ForegroundColor White
    exit 1
}
Write-Host "cloudflared installed" -ForegroundColor Green

try {
    $healthCheck = Invoke-WebRequest -Uri "http://localhost:8080/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    if ($healthCheck.Content -match '"status"\s*:\s*"ok"') {
        Write-Host "MCP server running on localhost:8080" -ForegroundColor Green
    } else {
        Write-Host "MCP server responded but health check unexpected: $($healthCheck.Content)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "MCP server not responding on localhost:8080" -ForegroundColor Red
    Write-Host "Start Docker containers first: docker compose up -d" -ForegroundColor White
    exit 1
}
Write-Host ""

$originCertPath = $env:TUNNEL_ORIGIN_CERT
if ([string]::IsNullOrWhiteSpace($originCertPath)) {
    $defaultOriginCert = Join-Path $env:USERPROFILE ".cloudflared\cert.pem"
    if (Test-Path $defaultOriginCert) {
        $originCertPath = $defaultOriginCert
    }
}

if ([string]::IsNullOrWhiteSpace($originCertPath)) {
    Write-Host "Cloudflare origin cert not found (~/.cloudflared/cert.pem)" -ForegroundColor Red
    Write-Host "Run this first: cloudflared tunnel login" -ForegroundColor White
    Write-Host "Then rerun: .\setup-tunnel.ps1" -ForegroundColor White
    exit 1
}

if (-not (Test-Path $originCertPath)) {
    Write-Host "Configured origin cert path does not exist: $originCertPath" -ForegroundColor Red
    Write-Host "Fix TUNNEL_ORIGIN_CERT or run: cloudflared tunnel login" -ForegroundColor White
    exit 1
}

Write-Host "Cloudflare origin cert found" -ForegroundColor Green
Write-Host ""

$configPath = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
if (Test-Path $configPath) {
    $backupPath = Join-Path $env:USERPROFILE (".cloudflared\config.backup.{0}.yml" -f (Get-Date -Format "yyyyMMddHHmmss"))
    Move-Item -Path $configPath -Destination $backupPath -Force
    Write-Host "Existing config.yml moved to backup: $backupPath" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "Step 1: Cloudflare login" -ForegroundColor Yellow
Write-Host "Already authenticated (origin cert present)" -ForegroundColor Green
Write-Host ""

Write-Host "Step 2: Create or reuse tunnel 'notion-mcp'" -ForegroundColor Yellow
$existingTunnels = cloudflared tunnel list 2>&1 | Out-String
$tunnelUUID = $null

if ($existingTunnels -match '([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\s+notion-mcp') {
    $tunnelUUID = $Matches[1]
    Write-Host "Tunnel already exists: $tunnelUUID (reusing)" -ForegroundColor Green
} else {
    Write-Host "Creating new tunnel..." -ForegroundColor White
    $createOutput = cloudflared tunnel create notion-mcp 2>&1 | Out-String
    Write-Host $createOutput

    if ($createOutput -match '([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})') {
        $tunnelUUID = $Matches[1]
        Write-Host "Tunnel created: $tunnelUUID" -ForegroundColor Green
    }
}

if ([string]::IsNullOrWhiteSpace($tunnelUUID)) {
    $existingTunnels = cloudflared tunnel list 2>&1 | Out-String
    if ($existingTunnels -match '([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\s+notion-mcp') {
        $tunnelUUID = $Matches[1]
    }
}

if ([string]::IsNullOrWhiteSpace($tunnelUUID)) {
    Write-Host "Failed to resolve tunnel UUID for notion-mcp" -ForegroundColor Red
    exit 1
}
Write-Host ""

Write-Host "Step 3: Route DNS mcp.tenantsage.org" -ForegroundColor Yellow
$dnsOutput = cloudflared tunnel route dns notion-mcp mcp.tenantsage.org 2>&1 | Out-String
$expectedCName = "$tunnelUUID.cfargotunnel.com"
if ($dnsOutput -match 'already exists' -or $LASTEXITCODE -eq 0) {
    Write-Host "DNS routed (or already exists)" -ForegroundColor Green
} else {
    Write-Host "DNS route failed; continuing with local tunnel setup" -ForegroundColor Yellow
    Write-Host $dnsOutput -ForegroundColor Gray
    Write-Host ""
    Write-Host "To fix manually, add this CNAME in Cloudflare:" -ForegroundColor White
    Write-Host "  Name: mcp" -ForegroundColor Gray
    Write-Host "  Target: $expectedCName" -ForegroundColor Yellow
}
Write-Host ""

try {
    $mcpResolve = [System.Net.Dns]::GetHostEntry("mcp.tenantsage.org")
    if ($mcpResolve) {
        $resolvedCName = (nslookup mcp.tenantsage.org 8.8.8.8 2>$null | Select-String "canonical name").ToString()
        if ($resolvedCName -match "cfargotunnel\.com") {
            Write-Host "DNS verification: mcp.tenantsage.org resolves correctly" -ForegroundColor Green
        } elseif ($resolvedCName) {
            Write-Host "DNS warning: mcp.tenantsage.org resolves to: $resolvedCName" -ForegroundColor Yellow
            Write-Host "Expected: $tunnelUUID.cfargotunnel.com" -ForegroundColor Gray
        }
    }
} catch {
}
Write-Host ""

Write-Host "Step 4: Creating config.yml" -ForegroundColor Yellow
$credentialsPath = "$env:USERPROFILE\.cloudflared\$tunnelUUID.json"
if (-not (Test-Path $credentialsPath)) {
    Write-Host "Credentials file not found: $credentialsPath" -ForegroundColor Red
    Write-Host "Expected location for tunnel $tunnelUUID" -ForegroundColor White
    exit 1
}

$configLines = @(
    "tunnel: $tunnelUUID"
    "credentials-file: '$credentialsPath'"
    ""
    "ingress:"
    "  - hostname: mcp.tenantsage.org"
    "    service: http://localhost:8080"
    "  - service: http_status:404"
)
$configLines | Set-Content $configPath -Encoding UTF8

Write-Host "Config saved to: $configPath" -ForegroundColor Green
Write-Host ""

Write-Host "Step 5: Starting tunnel..." -ForegroundColor Yellow
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Gray
Write-Host "Your MCP server will be available at: https://mcp.tenantsage.org" -ForegroundColor Green
Write-Host "Keep this window open. The tunnel runs here." -ForegroundColor Yellow
Write-Host ("=" * 60) -ForegroundColor Gray
Write-Host ""
Write-Host "Security reminders:" -ForegroundColor Cyan
Write-Host "  API key auth enforced (X-API-Key header required)" -ForegroundColor White
Write-Host "  Rate limiting enabled (60 req/min per key)" -ForegroundColor White
Write-Host "  Database not exposed publicly" -ForegroundColor White
Write-Host "  /health endpoint returns status only" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop the tunnel" -ForegroundColor Gray
Write-Host ""

cloudflared tunnel run notion-mcp
