#!/bin/bash
set -e

# Create mcp_app user with the same password as postgres for simplicity
# In production, use a separate strong password from secret manager
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_app') THEN
        CREATE ROLE mcp_app LOGIN PASSWORD '$POSTGRES_PASSWORD';
      END IF;
    END
    \$\$;

    -- Grant database connection
    GRANT CONNECT ON DATABASE $POSTGRES_DB TO mcp_app;
    
    -- Grant schema usage
    GRANT USAGE ON SCHEMA public TO mcp_app;
    
    -- Grant table permissions (will be applied to tables created by schema.sql)
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mcp_app;
    
    -- Grant sequence permissions
    GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO mcp_app;
    
    -- Set default privileges for future objects
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mcp_app;
    
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
      GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO mcp_app;
EOSQL

echo "✅ Created mcp_app user with proper permissions"
