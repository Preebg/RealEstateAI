-- Per-user acceptance of current Terms + Privacy effective dates.
-- Safe to re-run on existing volumes (init scripts only run on first Postgres start).

CREATE TABLE IF NOT EXISTS public.legal_acceptances (
  user_id uuid PRIMARY KEY,
  privacy_effective_date date NOT NULL,
  terms_effective_date date NOT NULL,
  accepted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS legal_acceptances_accepted_at_idx
  ON public.legal_acceptances (accepted_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.legal_acceptances TO capeigen_app;

NOTIFY pgrst, 'reload schema';
