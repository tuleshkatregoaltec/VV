#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS auth;
    GRANT ALL ON SCHEMA auth TO $POSTGRES_USER;

    -- Create postgres role if it doesn't exist (needed by GoTrue migrations)
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'postgres') THEN
            CREATE ROLE postgres WITH LOGIN SUPERUSER;
        END IF;
    END
    \$\$;
EOSQL
