-- PostgREST role: full access on public schema (API enforces auth).

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'capeigen_authenticator') THEN
    CREATE ROLE capeigen_authenticator NOINHERIT LOGIN PASSWORD 'capeigen_authenticator';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'capeigen_app') THEN
    CREATE ROLE capeigen_app NOLOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO capeigen_authenticator;
GRANT USAGE ON SCHEMA public TO capeigen_app;
GRANT capeigen_app TO capeigen_authenticator;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO capeigen_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO capeigen_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO capeigen_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO capeigen_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO capeigen_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO capeigen_app;
