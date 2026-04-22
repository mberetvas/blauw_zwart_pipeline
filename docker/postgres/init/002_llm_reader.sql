-- Provision a read-only role for the LLM API service.
-- Runs once at container init; executed by the postgres superuser.
-- The llm_reader role gets SELECT on every current and future table/view
-- in the dbt marts schema. The schema is pre-created here so grants and
-- default-privilege rules are in place before dbt materialises anything.
\getenv llm_reader_password LLM_READER_PASSWORD
\if :{?llm_reader_password}
\else
\set llm_reader_password 'llm_reader_pass'
\endif

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'llm_reader') AS llm_reader_exists
\gset
\if :llm_reader_exists
ALTER ROLE llm_reader WITH LOGIN PASSWORD :'llm_reader_password';
\else
CREATE ROLE llm_reader LOGIN PASSWORD :'llm_reader_password';
\endif

-- Allow connection to the application database.
SELECT current_database() AS current_db
\gset
GRANT CONNECT ON DATABASE :"current_db" TO llm_reader;

-- Pre-create the dbt target schema so grants work before dbt runs for the first time.
CREATE SCHEMA IF NOT EXISTS dbt_dev;

-- Schema-level access.
GRANT USAGE ON SCHEMA dbt_dev TO llm_reader;

-- Tables that already exist (none on a fresh volume; safe to run on re-init).
GRANT SELECT ON ALL TABLES IN SCHEMA dbt_dev TO llm_reader;

-- Future tables/views materialised by dbt (runs as the postgres superuser,
-- so ALTER DEFAULT PRIVILEGES for the current role covers all dbt output).
ALTER DEFAULT PRIVILEGES IN SCHEMA dbt_dev
    GRANT SELECT ON TABLES TO llm_reader;

-- Ensure LLM-generated SQL does not need a schema prefix.
ALTER ROLE llm_reader SET search_path = dbt_dev;
