# Environment Variables & Secrets Security Guide

## Changes Made

### 1. Removed `env_file` from db service
- **Before**: `db` service loaded `mcp_server/.env` unnecessarily
- **After**: `db` only uses `POSTGRES_PASSWORD` via `environment:` section
- **Why**: Database service should only receive its own credentials, not application secrets

### 2. Added Redis authentication
- **Before**: Redis had no password requirement despite URL containing credentials
- **After**: Redis enforces `--requirepass ${REDIS_PASSWORD}` via command
- **Why**: Prevents unauthorized access even if network is exposed accidentally

### 3. Separated REDIS_PASSWORD in .env
- **New variable**: `REDIS_PASSWORD=xFF7U54yVNs_mwc3DbIEZjUBf25WfVtEOwQWf2X205U`
- **Why**: Allows docker-compose to inject password into Redis command independently

## Environment Variable Locations

```
mcp service:          .env file (via env_file:)
db service:           environment: section (POSTGRES_PASSWORD only)
redis service:        environment: section (REDIS_PASSWORD only)
```

## Security Best Practices

### ✅ Already Implemented
- `.env` file in `.gitignore` (prevents accidental commits)
- `env_file:` used for application-specific secrets
- Services on internal networks (db, redis not exposed)
- Read-only filesystem on mcp container
- Capability dropping on mcp container
- Health checks for all services

### ⚠️ For Production Deployment

1. **Use Docker Secrets** (if deploying with Docker Swarm)
   ```yaml
   secrets:
     postgres_password:
       external: true
     redis_password:
       external: true
   
   services:
     db:
       secrets:
         - postgres_password
   ```

2. **Use orchestrator secrets** (if deploying with Kubernetes)
   - Store secrets in `kubectl` and mount as environment variables

3. **Rotate credentials regularly**
   - NOTION_TOKEN
   - RAG_SERVER_SECRET
   - ACTOR_SIGNING_SECRET
   - POSTGRES_PASSWORD
   - REDIS_PASSWORD

4. **Use .env.example** (safe version for developers)
   ```bash
   NOTION_TOKEN=<your-notion-token-here>
   POSTGRES_PASSWORD=<secure-password>
   REDIS_PASSWORD=<secure-password>
   # ... (other vars without actual secrets)
   ```

5. **Audit .env access**
   - Only necessary team members should have access
   - Store backups in secure vault (AWS Secrets Manager, HashiCorp Vault, etc.)

6. **Environment-specific configurations**
   ```
   mcp_server/.env          (local development)
   mcp_server/.env.prod     (production secrets)
   mcp_server/.env.staging  (staging secrets)
   ```

## Testing Changes

After updating docker-compose.yml:

```bash
# Validate syntax
docker compose config

# Rebuild and restart
docker compose down
docker compose up --build

# Check mcp can connect to Redis (if using --scale profile)
docker compose --profile scale up redis
docker exec notionmcp-mcp-1 redis-cli -u "redis://:${REDIS_PASSWORD}@redis:6379/0" ping
```

## Variable Reference

| Variable | Used By | Purpose |
|----------|---------|---------|
| NOTION_TOKEN | mcp | Notion API authentication |
| POSTGRES_PASSWORD | db, mcp | Database access credentials |
| REDIS_PASSWORD | redis, mcp | Redis authentication |
| RAG_DATABASE_URL | mcp | Database connection string |
| RAG_SERVER_SECRET | mcp | HMAC-SHA256 signing |
| RAG_API_KEYS | mcp | API key validation |
| ACTOR_SIGNING_SECRET | mcp | Actor request signing |
| GOVERNANCE_DB_ID, WORKFLOW_DB_ID, etc. | mcp | Notion database IDs |

## Files Modified

- `docker-compose.yml` — Removed db env_file, added Redis requirepass
- `mcp_server/.env` — Added REDIS_PASSWORD variable
- `.gitignore` — Already covers .env files ✓
