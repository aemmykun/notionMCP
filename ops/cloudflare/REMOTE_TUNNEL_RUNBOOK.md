# Remote Tunnel Runbook

This runbook is operator-only deployment guidance for exposing the MCP server through a remotely managed Cloudflare Tunnel.

It is not part of the sellable runtime package.

## Boundary

- The product runtime is the MCP application and its required environment variables.
- Cloudflare Tunnel, DNS, API tokens, tunnel tokens, and `cloudflared` service installation belong to the operator infrastructure layer.
- Do not bundle Cloudflare credentials, `cloudflared` binaries, local tunnel configs, or tunnel tokens into customer-facing artifacts.

## Preconditions

- The MCP server is reachable locally at `http://localhost:8080`.
- The target DNS zone is managed in Cloudflare.
- The host can reach Cloudflare outbound on port `7844`.
- You have a Cloudflare API token with:
  - `Account / Cloudflare Tunnel / Edit`
  - `Zone / DNS / Edit`

## Create The Tunnel

Set these variables first:

```bash
export ACCOUNT_ID="<cloudflare-account-id>"
export ZONE_ID="<cloudflare-zone-id>"
export CLOUDFLARE_API_TOKEN="<api-token>"
```

For Windows PowerShell, prefer `Invoke-RestMethod` over `curl` because `curl` is often an alias for `Invoke-WebRequest` and behaves differently from shell curl.

```powershell
$ACCOUNT_ID = "<cloudflare-account-id>"
$CLOUDFLARE_API_TOKEN = "<api-token>"
$headers = @{
  Authorization = "Bearer $CLOUDFLARE_API_TOKEN"
  "Content-Type" = "application/json"
}
```

To look up the Zone ID for `tenantsage.org`:

```powershell
$zone = Invoke-RestMethod `
  -Method Get `
  -Uri "https://api.cloudflare.com/client/v4/zones?name=tenantsage.org" `
  -Headers $headers

$ZONE_ID = $zone.result[0].id
$ZONE_ID
```

Create a remotely managed tunnel:

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel" \
  --request POST \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --json '{
    "name": "notion-mcp",
    "config_src": "cloudflare"
  }'
```

  PowerShell equivalent:

  ```powershell
  $createBody = @{
    name = "notion-mcp"
    config_src = "cloudflare"
  } | ConvertTo-Json

  $createResponse = Invoke-RestMethod `
    -Method Post `
    -Uri "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel" `
    -Headers $headers `
    -Body $createBody

  $TUNNEL_ID = $createResponse.result.id
  $TUNNEL_TOKEN = $createResponse.result.token
  ```

Persist these returned values securely:

- `result.id`
- `result.token`

## Publish The MCP Application

Push ingress configuration to Cloudflare:

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
  --request PUT \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --json '{
    "config": {
      "ingress": [
        {
          "hostname": "mcp.tenantsage.org",
          "service": "http://localhost:8080",
          "originRequest": {}
        },
        {
          "service": "http_status:404"
        }
      ]
    }
  }'
```

  PowerShell equivalent:

  ```powershell
  $configBody = @{
    config = @{
      ingress = @(
        @{
          hostname = "mcp.tenantsage.org"
          service = "http://localhost:8080"
          originRequest = @{}
        },
        @{
          service = "http_status:404"
        }
      )
    }
  } | ConvertTo-Json -Depth 6

  Invoke-RestMethod `
    -Method Put `
    -Uri "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" `
    -Headers $headers `
    -Body $configBody
  ```

Create the proxied DNS record:

```bash
curl "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  --request POST \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --json '{
    "type": "CNAME",
    "proxied": true,
    "name": "mcp.tenantsage.org",
    "content": "'$TUNNEL_ID'.cfargotunnel.com"
  }'
```

  PowerShell equivalent:

  ```powershell
  $dnsBody = @{
    type = "CNAME"
    proxied = $true
    name = "mcp.tenantsage.org"
    content = "$TUNNEL_ID.cfargotunnel.com"
  } | ConvertTo-Json

  Invoke-RestMethod `
    -Method Post `
    -Uri "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" `
    -Headers $headers `
    -Body $dnsBody
  ```

## Install The Connector As A Windows Service

Install `cloudflared` on the operator host, then run:

```powershell
cloudflared service install <TUNNEL_TOKEN>
Start-Service cloudflared
Get-Service cloudflared
```

This keeps the tunnel running without an open terminal.

## Verify

Verify tunnel health through the API:

```bash
curl "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID" \
  --request GET \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

PowerShell equivalent:

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID" `
    -Headers $headers
```

Healthy state should show active connections and a healthy status.

Then verify the application path:

```bash
curl https://mcp.tenantsage.org/health
```

PowerShell equivalent:

```powershell
Invoke-WebRequest -Uri "https://mcp.tenantsage.org/health" -UseBasicParsing
```

Expected response:

```json
{"status":"ok"}
```

## Security Notes

- Keep `CLOUDFLARE_API_TOKEN` and `TUNNEL_TOKEN` out of the repository and out of customer deliverables.
- Do not package `.cloudflared`, `config.yml`, origin certs, or tunnel JSON credentials with the application.
- Public exposure through Cloudflare does not replace application authentication. `X-API-Key` and actor-signing controls remain mandatory at the MCP layer.
- Avoid pasting live API tokens or tunnel tokens into chat transcripts, committed files, or shared runbooks.

## Current Production State

- Hostname: `mcp.tenantsage.org`
- Production tunnel name: `notion-mcp-managed`
- Production tunnel ID: `f292e4ad-85c9-4170-a64a-a014b3f0cdb7`
- Config source: `cloudflare` (remote-managed)
- Origin service: `http://localhost:8080`
- Connector mode: Windows `cloudflared` service on the operator host
- Legacy local-managed tunnel `notion-mcp` was removed after cutover

## Required Secret Hygiene After Setup

- If a Cloudflare API token was pasted into chat, terminals, or shared notes, rotate it in the Cloudflare dashboard.
- If a tunnel token was pasted into chat, terminals, or shared notes, refresh the tunnel token in Cloudflare and reinstall the `cloudflared` service with the new token.
- After refreshing a compromised tunnel token, remove stale connections with the Cloudflare tunnel connections cleanup API before confirming final state.
