#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=reader_password="$XRB_READER_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE xrb_reader LOGIN PASSWORD %L', :'reader_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'xrb_reader') \gexec
GRANT CONNECT ON DATABASE xrb TO xrb_reader;
GRANT USAGE ON SCHEMA public TO xrb_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE xrb IN SCHEMA public GRANT SELECT ON TABLES TO xrb_reader;
ALTER ROLE xrb_reader SET default_transaction_read_only = on;
SQL
