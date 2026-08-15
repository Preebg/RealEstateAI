-- All-user usage telemetry + admin-editable legal documents.
-- Safe to re-run on existing volumes (init scripts only run on first Postgres start).

ALTER TABLE public.preview_events
  ADD COLUMN IF NOT EXISTS is_preview boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS preview_events_event_type_created_at_idx
  ON public.preview_events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS preview_events_is_preview_created_at_idx
  ON public.preview_events (is_preview, created_at DESC);
CREATE INDEX IF NOT EXISTS preview_events_path_created_at_idx
  ON public.preview_events (path, created_at DESC)
  WHERE path IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.legal_documents (
  slug text PRIMARY KEY CHECK (slug = ANY (ARRAY['terms'::text, 'privacy'::text])),
  title text NOT NULL,
  body text NOT NULL,
  effective_date date NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.legal_documents TO capeigen_app;

NOTIFY pgrst, 'reload schema';
