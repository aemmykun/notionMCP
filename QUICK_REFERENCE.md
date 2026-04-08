# Quick Reference Card - MCP Server Operations

## 🚀 Daily Operations

### Check Service Health

```powershell
# Local health
curl.exe http://127.0.0.1:8080/health

# Public health (through tunnel)
curl.exe https://mcp.tenantsage.org/health

# Docker services
cd "c:\Users\arthi\notion mcp"
docker compose ps
```

### View Logs

```powershell
# Last 100 lines
docker compose logs mcp --tail=100

# Follow logs (Ctrl+C to stop)
docker compose logs mcp --follow

# Filter for errors
docker compose logs mcp | Select-String "ERROR|CRITICAL"
```

### Restart Services

```powershell
# Restart MCP only
docker compose restart mcp

# Restart all services
docker compose restart

# Full rebuild if config changed
docker compose up -d --build
```

---

## 🔐 Security Operations

### Run Security Scan

```powershell
cd mcp_server
.\venv\Scripts\Activate.ps1

# Install tools (first time only)
.\install_security_tools.ps1

# Run scan
python security_scan.py

# Fail on high-severity (for CI)
python security_scan.py --fail-on-high
```

### Production Preflight Check

```powershell
cd mcp_server
python production_preflight.py --strict
```

### Check Cloudflare Tunnel

```powershell
# Service status
Get-Service cloudflared

# Recent events
Get-EventLog -LogName Application -Source cloudflared -Newest 5
```

---

## 🧪 Testing

### Run All Tests

```powershell
cd mcp_server
.\venv\Scripts\Activate.ps1
pytest -v
```

### Run Specific Test Suites

```powershell
# Unit tests only
pytest test_server.py -v

# RLS security tests (needs DB)
pytest test_rls_fail_closed.py -v

# Production security proofs (needs DB)
pytest test_production_security_proof.py -v

# Quick smoke test
pytest test_server.py test_production_preflight.py -q
```

### Code Coverage

```powershell
pytest --cov=. --cov-report=html
# Open htmlcov/index.html
```

---

## 💾 Backup & Restore

### Manual Backup

```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
docker compose exec -T db pg_dump -U postgres notion_mcp > "backup_$timestamp.sql"
```

### Quick Restore (⚠️ OVERWRITES DATA)

```powershell
# Stop app
docker compose stop mcp

# Restore
Get-Content backup.sql | docker compose exec -T db psql -U postgres -d notion_mcp

# Restart app
docker compose start mcp
```

---

## 🔑 API Key Management

### Generate New Key

```powershell
cd mcp_server
python generate_api_key.py "workspace-name"

# Save both outputs:
# 1. Plaintext key (for client)
# 2. HMAC entry (add to .env RAG_API_KEYS)
```

### Rotate Key (Zero Downtime)

```powershell
# 1. Add new key to .env (keep old)
# RAG_API_KEYS=old_hmac:uuid,new_hmac:uuid

# 2. Restart
docker compose restart mcp

# 3. Update clients with new key

# 4. After grace period, remove old key
# RAG_API_KEYS=new_hmac:uuid
docker compose restart mcp
```

---

## 📊 Monitoring

### Database Status

```powershell
# Connection test
docker compose exec db pg_isready -U postgres

# Row counts
docker compose exec db psql -U postgres -d notion_mcp -c "
SELECT 
  'rag_sources' AS table, COUNT(*) FROM rag_sources
UNION ALL SELECT
  'rag_chunks', COUNT(*) FROM rag_chunks
"
```

### Resource Usage

```powershell
# Container stats
docker stats notionmcp-mcp-1 notionmcp-db-1 --no-stream

# Disk usage
docker system df
```

---

## 🛠️ Troubleshooting

### Service Won't Start

```powershell
# 1. Check logs
docker compose logs mcp --tail=50

# 2. Verify .env file exists
Test-Path mcp_server\.env

# 3. Check port availability
Test-NetConnection -ComputerName localhost -Port 8080
```

### Database Connection Failed

```powershell
# 1. Is DB healthy?
docker compose exec db pg_isready -U postgres

# 2. Can MCP reach it?
docker compose exec mcp python -c "
import os, psycopg2
conn = psycopg2.connect(os.getenv('RAG_DATABASE_URL'))
print('✅ Connection OK')
"
```

### Tunnel Not Working

```powershell
# 1. Check service
Get-Service cloudflared

# 2. Restart tunnel
Restart-Service cloudflared

# 3. Test local endpoint first
curl.exe http://127.0.0.1:8080/health

# 4. Then test public
curl.exe https://mcp.tenantsage.org/health
```

---

## 🚨 Emergency Procedures

### Immediate Rollback

```powershell
# 1. Stop current version
docker compose down

# 2. Restore from backup (see Backup section)

# 3. Start previous version
git checkout <previous-commit>
docker compose up -d
```

### Clear Cache and Rebuild

```powershell
# Nuclear option - full rebuild
docker compose down -v
docker compose build --no-cache
docker compose up -d

# Verify health
curl.exe https://mcp.tenantsage.org/health
```

---

## 📞 Quick Contacts

| Issue Type | Action |
| --- | --- |
| Service Down | Check health, view logs, restart |
| Database Issues | Run pg_isready, check logs |
| Tunnel Issues | Restart cloudflared service |
| Security Alert | Run security_scan.py, check CVEs |
| Performance | Check docker stats, review logs |

---

## 📚 Full Documentation

- **Operations**: `mcp_server/OPERATIONS.md`
- **QA Report**: `QA_ENGINEERING_REPORT.md`
- **Release Notes**: `mcp_server/RELEASE_NOTES.md`
- **Client Integration**: `mcp_server/CLIENT_INTEGRATION_MANUAL.md`
- **Tunnel Setup**: `ops/cloudflare/REMOTE_TUNNEL_RUNBOOK.md`

---

**Last Updated**: April 8, 2026  
**Keep This Handy**: Print or bookmark for quick reference
