-- CapEigen local Postgres schema (self-hosted harvest machine).
-- No auth.users FKs — Auth stays on Supabase; UUIDs are validated in the API.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS public.properties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  address text NOT NULL UNIQUE,
  price numeric,
  year_built numeric,
  rent numeric,
  tax_rate numeric,
  hoa numeric,
  insurance numeric,
  summary text,
  maint_percent numeric,
  predicted_value numeric,
  prediction_reasoning text,
  location_score numeric,
  property_label text,
  quantum_risk_score double precision,
  sources jsonb,
  timestamp timestamptz DEFAULT now(),
  user_id uuid,
  original_ai_rent numeric,
  original_ai_maint numeric,
  is_outlier boolean NOT NULL DEFAULT false,
  override_notes text,
  market_city text,
  state_code text,
  zip_code text,
  square_footage numeric,
  property_condition text,
  property_category text,
  from_kb boolean NOT NULL DEFAULT false,
  appreciation_forecast numeric,
  forecast_rate numeric,
  forecast_growth numeric,
  ai_vacancy_rate numeric,
  ai_management_fee numeric,
  monthly_net_cash_flow numeric,
  comps_analysis jsonb,
  latitude double precision,
  longitude double precision,
  geocode_confidence text,
  geocode_source text,
  geocode_model text,
  maps_place_id text,
  maps_uri text,
  environmental_risk jsonb,
  is_turnkey boolean NOT NULL DEFAULT false,
  turnkey_identified_at timestamptz,
  rent_comps_analysis jsonb,
  email_drafted boolean NOT NULL DEFAULT false,
  strategy_tag text,
  outreach_agent_email text,
  primary_image_url text,
  image_urls jsonb,
  listing_url text,
  listing_status text,
  days_on_market integer,
  view_count integer,
  discord_alert_sent_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.archived_properties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  address text NOT NULL,
  price numeric,
  year_built numeric,
  rent numeric,
  tax_rate numeric,
  hoa numeric,
  insurance numeric,
  summary text,
  maint_percent numeric,
  predicted_value numeric,
  prediction_reasoning text,
  location_score numeric,
  property_label text,
  quantum_risk_score double precision,
  sources jsonb,
  timestamp timestamptz DEFAULT now(),
  user_id uuid,
  original_ai_rent numeric,
  original_ai_maint numeric,
  is_outlier boolean NOT NULL DEFAULT false,
  override_notes text,
  market_city text,
  state_code text,
  zip_code text,
  square_footage numeric,
  property_condition text,
  property_category text,
  from_kb boolean NOT NULL DEFAULT false,
  appreciation_forecast numeric,
  forecast_rate numeric,
  forecast_growth numeric,
  ai_vacancy_rate numeric,
  ai_management_fee numeric,
  monthly_net_cash_flow numeric,
  comps_analysis jsonb,
  latitude double precision,
  longitude double precision,
  geocode_confidence text,
  geocode_source text,
  geocode_model text,
  maps_place_id text,
  maps_uri text,
  environmental_risk jsonb,
  is_turnkey boolean NOT NULL DEFAULT false,
  turnkey_identified_at timestamptz,
  rent_comps_analysis jsonb,
  email_drafted boolean NOT NULL DEFAULT false,
  strategy_tag text,
  outreach_agent_email text,
  primary_image_url text,
  image_urls jsonb,
  listing_url text,
  listing_status text,
  days_on_market integer,
  view_count integer,
  discord_alert_sent_at timestamptz,
  archived_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS archived_properties_address_key
  ON public.archived_properties (address);
CREATE INDEX IF NOT EXISTS idx_archived_properties_archived_at
  ON public.archived_properties (archived_at DESC);

CREATE TABLE IF NOT EXISTS public.user_property_overrides (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  rent numeric,
  maint_percent numeric,
  vacancy_rate numeric,
  management_fee numeric,
  is_outlier boolean NOT NULL DEFAULT false,
  override_notes text NOT NULL DEFAULT '',
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, property_id)
);

CREATE TABLE IF NOT EXISTS public.user_saved_properties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  saved_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, property_id)
);

CREATE TABLE IF NOT EXISTS public.property_shares (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  share_token text NOT NULL UNIQUE,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  created_by uuid NOT NULL,
  include_assumptions boolean NOT NULL DEFAULT true,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.property_comparables (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  sort_order integer NOT NULL DEFAULT 0,
  address text,
  sale_price numeric,
  sale_date text,
  square_footage numeric,
  bedrooms text,
  bathrooms text,
  distance_miles text,
  comparison_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.property_share_comps (
  share_token text PRIMARY KEY REFERENCES public.property_shares (share_token) ON DELETE CASCADE,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  comps_analysis jsonb NOT NULL,
  predicted_value numeric,
  prediction_reasoning text,
  created_at timestamptz NOT NULL DEFAULT now(),
  rent_comps_analysis jsonb
);

CREATE TABLE IF NOT EXISTS public.user_notification_preferences (
  user_id uuid PRIMARY KEY,
  digest_enabled boolean NOT NULL DEFAULT true,
  last_digest_sent_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.recommendation_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  feedback text NOT NULL CHECK (feedback = ANY (ARRAY['like'::text, 'dislike'::text])),
  source text NOT NULL DEFAULT 'app' CHECK (source = ANY (ARRAY['app'::text, 'email'::text])),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, property_id)
);

CREATE TABLE IF NOT EXISTS public.digest_recommendation_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  digest_sent_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, property_id)
);

CREATE TABLE IF NOT EXISTS public.oauth_pkce_pending (
  session_id text PRIMARY KEY,
  code_verifier text NOT NULL,
  code_challenge text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS public.oauth_auth_handoff (
  handoff_id text PRIMARY KEY,
  access_token text NOT NULL,
  refresh_token text NOT NULL DEFAULT '',
  user_id uuid NOT NULL,
  user_email text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS public.app_runtime_config (
  key text PRIMARY KEY,
  value text NOT NULL
);

INSERT INTO public.app_runtime_config (key, value)
VALUES ('catalog_admin_user_id', '')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.preview_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  username text NOT NULL,
  event_type text NOT NULL,
  path text,
  label text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS preview_events_created_at_idx
  ON public.preview_events (created_at DESC);
CREATE INDEX IF NOT EXISTS preview_events_username_idx
  ON public.preview_events (username, created_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_properties_timestamp_active
  ON public.properties ("timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_properties_outreach_queue
  ON public.properties (email_drafted) WHERE (email_drafted = false);
CREATE INDEX IF NOT EXISTS idx_properties_outreach_agent_email
  ON public.properties (lower(outreach_agent_email)) WHERE (outreach_agent_email IS NOT NULL);
CREATE INDEX IF NOT EXISTS properties_turnkey_identified_idx
  ON public.properties (turnkey_identified_at DESC) WHERE (is_turnkey = true);

CREATE INDEX IF NOT EXISTS idx_user_property_overrides_property_id
  ON public.user_property_overrides (property_id);
CREATE INDEX IF NOT EXISTS idx_user_property_overrides_user_id
  ON public.user_property_overrides (user_id);
CREATE INDEX IF NOT EXISTS user_saved_properties_user_id_saved_at_idx
  ON public.user_saved_properties (user_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS property_shares_created_by_idx
  ON public.property_shares (created_by);
CREATE INDEX IF NOT EXISTS property_shares_token_idx
  ON public.property_shares (share_token);
CREATE INDEX IF NOT EXISTS property_comparables_property_id_idx
  ON public.property_comparables (property_id, sort_order);
CREATE INDEX IF NOT EXISTS recommendation_feedback_user_idx
  ON public.recommendation_feedback (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS digest_recommendation_log_user_idx
  ON public.digest_recommendation_log (user_id, digest_sent_at DESC);
CREATE INDEX IF NOT EXISTS oauth_pkce_pending_expires_at_idx
  ON public.oauth_pkce_pending (expires_at);
CREATE INDEX IF NOT EXISTS oauth_auth_handoff_expires_at_idx
  ON public.oauth_auth_handoff (expires_at);
