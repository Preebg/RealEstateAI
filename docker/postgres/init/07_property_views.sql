-- In-app viewership (unique users per listing) and Property of the Day impressions.
-- Distinct from properties.view_count, which stores portal listing views when harvested.
-- Safe to re-run on existing volumes (init scripts only run on first Postgres start).

ALTER TABLE public.properties
  ADD COLUMN IF NOT EXISTS app_view_count integer NOT NULL DEFAULT 0;

ALTER TABLE public.archived_properties
  ADD COLUMN IF NOT EXISTS app_view_count integer NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.property_app_views (
  user_id uuid NOT NULL,
  property_id uuid NOT NULL REFERENCES public.properties (id) ON DELETE CASCADE,
  first_viewed_at timestamptz NOT NULL DEFAULT now(),
  last_viewed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, property_id)
);

CREATE INDEX IF NOT EXISTS property_app_views_property_id_idx
  ON public.property_app_views (property_id);

CREATE INDEX IF NOT EXISTS properties_app_view_count_idx
  ON public.properties (app_view_count DESC);

CREATE TABLE IF NOT EXISTS public.property_of_day_impressions (
  user_id uuid NOT NULL,
  shown_on date NOT NULL,
  property_id uuid REFERENCES public.properties (id) ON DELETE SET NULL,
  shown_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, shown_on)
);

CREATE INDEX IF NOT EXISTS property_of_day_impressions_shown_on_idx
  ON public.property_of_day_impressions (shown_on DESC);
CREATE INDEX IF NOT EXISTS property_of_day_impressions_property_id_idx
  ON public.property_of_day_impressions (property_id);

CREATE OR REPLACE FUNCTION public.record_property_app_view(
  p_user_id uuid,
  p_property_id uuid
)
RETURNS integer
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
DECLARE
  v_inserted boolean := false;
  v_count integer := 0;
BEGIN
  IF p_user_id IS NULL OR p_property_id IS NULL THEN
    RETURN 0;
  END IF;

  INSERT INTO public.property_app_views (user_id, property_id)
  VALUES (p_user_id, p_property_id)
  ON CONFLICT (user_id, property_id)
  DO UPDATE SET last_viewed_at = now()
  RETURNING (xmax = 0) INTO v_inserted;

  IF v_inserted THEN
    UPDATE public.properties
    SET app_view_count = COALESCE(app_view_count, 0) + 1
    WHERE id = p_property_id
    RETURNING COALESCE(app_view_count, 0) INTO v_count;
  ELSE
    SELECT COALESCE(app_view_count, 0)
    INTO v_count
    FROM public.properties
    WHERE id = p_property_id;
  END IF;

  RETURN COALESCE(v_count, 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.archive_stale_properties(p_age_days integer DEFAULT 30)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_cutoff timestamptz := now() - make_interval(days => p_age_days);
  v_moved integer := 0;
BEGIN
  WITH stale AS (
    SELECT id FROM public.properties WHERE timestamp < v_cutoff
  ), upserted AS (
    INSERT INTO public.archived_properties (
      id, address, price, year_built, rent, tax_rate, hoa, insurance, summary,
      maint_percent, predicted_value, prediction_reasoning, location_score,
      property_label, quantum_risk_score, sources, timestamp, user_id,
      original_ai_rent, original_ai_maint, is_outlier, override_notes, market_city,
      state_code, zip_code, square_footage, property_condition, property_category,
      from_kb, appreciation_forecast, forecast_rate, forecast_growth,
      ai_vacancy_rate, ai_management_fee, monthly_net_cash_flow, comps_analysis,
      latitude, longitude, geocode_confidence, geocode_source, geocode_model,
      maps_place_id, maps_uri, environmental_risk, is_turnkey, turnkey_identified_at,
      rent_comps_analysis, email_drafted, strategy_tag, outreach_agent_email,
      primary_image_url, image_urls, listing_url, listing_status, days_on_market,
      view_count, app_view_count, discord_alert_sent_at, archived_at
    )
    SELECT
      p.id, p.address, p.price, p.year_built, p.rent, p.tax_rate, p.hoa, p.insurance,
      p.summary, p.maint_percent, p.predicted_value, p.prediction_reasoning,
      p.location_score, p.property_label, p.quantum_risk_score, p.sources, p.timestamp,
      p.user_id, p.original_ai_rent, p.original_ai_maint, p.is_outlier, p.override_notes,
      p.market_city, p.state_code, p.zip_code, p.square_footage, p.property_condition,
      p.property_category, p.from_kb, p.appreciation_forecast, p.forecast_rate,
      p.forecast_growth, p.ai_vacancy_rate, p.ai_management_fee, p.monthly_net_cash_flow,
      p.comps_analysis, p.latitude, p.longitude, p.geocode_confidence, p.geocode_source,
      p.geocode_model, p.maps_place_id, p.maps_uri, p.environmental_risk, p.is_turnkey,
      p.turnkey_identified_at, p.rent_comps_analysis, p.email_drafted, p.strategy_tag,
      p.outreach_agent_email, p.primary_image_url, p.image_urls, p.listing_url,
      p.listing_status, p.days_on_market, p.view_count, p.app_view_count,
      p.discord_alert_sent_at, now()
    FROM public.properties p WHERE p.id IN (SELECT id FROM stale)
    ON CONFLICT (id) DO UPDATE SET archived_at = EXCLUDED.archived_at
    RETURNING id
  )
  SELECT count(*)::integer INTO v_moved FROM upserted;

  DELETE FROM public.property_comparables
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.property_share_comps
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.user_saved_properties
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.user_property_overrides
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.recommendation_feedback
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.digest_recommendation_log
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.property_shares
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.property_app_views
  WHERE property_id IN (SELECT id FROM public.properties WHERE timestamp < v_cutoff);
  DELETE FROM public.properties WHERE timestamp < v_cutoff;
  RETURN v_moved;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.property_app_views TO capeigen_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.property_of_day_impressions TO capeigen_app;
GRANT EXECUTE ON FUNCTION public.record_property_app_view(uuid, uuid) TO capeigen_app;

NOTIFY pgrst, 'reload schema';
