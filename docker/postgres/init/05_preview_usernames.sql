-- Dashboard-managed preview/demo usernames. Safe to re-run on existing volumes.
-- Login allowlist is active rows here, with DEMO_USERNAMES as fallback.
-- Inactive rows block a name even if it remains in the environment.

CREATE TABLE IF NOT EXISTS public.preview_usernames (
  username_key text PRIMARY KEY,
  username text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS preview_usernames_active_idx
  ON public.preview_usernames (active, username);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.preview_usernames TO capeigen_app;

NOTIFY pgrst, 'reload schema';
