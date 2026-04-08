# Workspace Cleanup Guide

**Date**: April 8, 2026  
**Status**: Ready for review before cleanup

---

## Current Workspace State

### Files to KEEP (should commit first)

#### Documentation Files (created during QA)

- ✅ `QA_ENGINEERING_REPORT.md` - Comprehensive technical audit (50+ pages)
- ✅ `EXECUTIVE_SUMMARY.md` - Leadership brief with go/no-go recommendation
- ✅ `REPORTS_README.md` - Navigation guide for all reports
- ✅ `ACTION_ITEMS.md` - Progress tracker (8/12 complete)
- ✅ `IMPLEMENTATION_SUMMARY.md` - Completion report
- ✅ `QUICK_REFERENCE.md` - Operations cheat sheet
- ✅ `OPENAPI_GENERATION_REPORT.md` - API spec generation report
- ✅ `SECURITY.md` - Security policy

#### CI/CD and DevOps

- ✅ `.github/workflows/ci.yml` - Automated testing pipeline
- ✅ `.github/pull_request_template.md` - PR checklist

#### Operations and Security

- ✅ `mcp_server/OPERATIONS.md` - Day-to-day procedures (400+ lines)
- ✅ `mcp_server/security_scan.py` - Security scanning script
- ✅ `mcp_server/install_security_tools.ps1` - Security tools installer
- ✅ `mcp_server/requirements.lock` - Pinned dependencies
- ✅ `mcp_server/openapi/openapi.json` - API specification
- ✅ `mcp_server/openapi/README.md` - API docs guide

#### Test Files

- ✅ `mcp_server/test_metrics_endpoint.py` - Prometheus metrics tests

### Files Modified (review changes)

- `M .gitignore` - Review changes
- `M docker-compose.yml` - Review changes  
- `M mcp_server/README.md` - Review changes (added API docs section)
- `M mcp_server/requirements.txt` - Review changes
- `M mcp_server/server.py` - Review changes
- `M mcp_server/test_production_security_proof.py` - Review changes
- `M mcp_server/test_rls_fail_closed.py` - Review changes (fixed signature)

### Files to REMOVE (safe to delete)

These are already in .gitignore and will be removed by `git clean`:

#### Build Artifacts

- `.venv/` - Virtual environment (716 MB likely)
- `mcp_server/venv/` - Old virtual environment
- `mcp_server/__pycache__/` - Python bytecode cache
- `mcp_server/integration_tests/__pycache__/` - Test bytecode cache
- `mcp_server/.pytest_cache/` - Pytest cache
- `mcp_server/notion_mcp_server.egg-info/` - Package metadata
- `mcp_server/integration_tests.egg-info/` - Package metadata

#### Credentials (DO NOT COMMIT)

- `mcp_server/.env` - Contains secrets (already in .gitignore)

---

## Recommended Cleanup Procedure

### Step 1: Review Uncommitted Changes

```powershell
cd "c:\Users\arthi\notion mcp"
git status
git diff  # Review all modifications
```

### Step 2: Stage Documentation and Tools

```bash
# Add all new QA documentation
git add QA_ENGINEERING_REPORT.md EXECUTIVE_SUMMARY.md REPORTS_README.md
git add ACTION_ITEMS.md IMPLEMENTATION_SUMMARY.md QUICK_REFERENCE.md
git add OPENAPI_GENERATION_REPORT.md SECURITY.md

# Add CI/CD and DevOps
git add .github/
git add mcp_server/OPERATIONS.md
git add mcp_server/security_scan.py
git add mcp_server/install_security_tools.ps1
git add mcp_server/requirements.lock
git add mcp_server/openapi/

# Add test files
git add mcp_server/test_metrics_endpoint.py
```

### Step 3: Review Modified Files

```bash
# Review each modified file
git diff .gitignore
git diff docker-compose.yml
git diff mcp_server/README.md
git diff mcp_server/requirements.txt
git diff mcp_server/server.py
git diff mcp_server/test_production_security_proof.py
git diff mcp_server/test_rls_fail_closed.py

# If changes look good, stage them
git add .gitignore docker-compose.yml mcp_server/README.md
git add mcp_server/requirements.txt mcp_server/server.py
git add mcp_server/test_production_security_proof.py mcp_server/test_rls_fail_closed.py
```

### Step 4: Commit Everything

```bash
git commit -m "Complete QA assessment and technical debt cleanup

- Add comprehensive QA reports (engineering + executive)
- Implement CI/CD pipeline with 4-stage validation
- Add operations guide with backup/restore/incident response
- Add security scanning tools (pip-audit, bandit, safety)
- Generate OpenAPI 3.1.0 specification
- Lock dependencies for reproducible builds
- Fix test harness signature mismatches

Progress: 8/12 action items complete (67%)
"
```

### Step 5: Clean Build Artifacts

```powershell
# AFTER committing, remove build artifacts and caches
cd "c:\Users\arthi\notion mcp"

# Preview what will be removed
git clean -xdn

# If preview looks good (only .venv, __pycache__, .env, etc.), execute:
git clean -xdf

# This will remove:
# - .venv/ (716+ MB)
# - mcp_server/venv/
# - __pycache__/ directories
# - .pytest_cache/
# - *.egg-info/ directories
# - mcp_server/.env (SAFE - already backed up elsewhere)
```

### Step 6: Verify Clean State

```bash
git status  # Should show "working tree clean"
ls -la     # Verify documentation still exists
docker compose ps  # Verify services still running
```

---

## Safety Checks

### Before Running git clean

✅ **MUST DO**:

1. Commit all new documentation files
2. Commit all new tools and scripts
3. Backup `.env` file contents (contains secrets)
4. Verify services are running (`docker compose ps`)

❌ **DO NOT**:

1. Run `git clean` before committing new files
2. Commit the `.env` file (contains secrets)
3. Delete files you're not sure about

### If You Accidentally Clean

If you run `git clean -xdf` before committing:

```powershell
# Virtual environments can be recreated
cd mcp_server
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env file - restore from backup or regenerate secrets
# See README.md for setup instructions
```

---

## Expected Results

### Before Cleanup

- **Files changed**: 23
- **Files to remove**: 24 (mostly build artifacts)
- **Disk space used**: ~750 MB (virtual environments)

### After Cleanup

- **Files changed**: 0 (all committed)
- **Files to remove**: 0
- **Disk space freed**: ~700-750 MB

---

## Workspace Statistics

```powershell
# Check workspace health
git status --short | Measure-Object -Line         # Changed files
git clean -xdn | Measure-Object -Line              # Removable files
du -sh .venv                                        # Virtual env size
du -sh mcp_server/venv                             # Old virtual env size
docker compose ps                                   # Service status
```

---

## Alternative: Selective Cleanup

If you want to keep virtual environments but clean caches:

```powershell
# Remove only Python caches
Get-ChildItem -Path . -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Recurse -Filter ".pytest_cache" -Directory | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Recurse -Filter "*.egg-info" -Directory | Remove-Item -Recurse -Force

# Verify
git status --short
```

---

**⚠️ CRITICAL**: Do NOT run `git clean -xdf` until you've committed all documentation files!

**Recommendation**: First run the git add commands above, commit, then clean.

---

**Last Updated**: April 8, 2026  
**Next Action**: Review modified files and commit before cleanup
