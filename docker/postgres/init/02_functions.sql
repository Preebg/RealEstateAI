-- Trusted local helpers. AuthZ is enforced in FastAPI; PostgREST uses one app role.

CREATE OR REPLACE FUNCTION public.catalog_admin_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  SELECT NULLIF(value, '')::uuid
  FROM public.app_runtime_config
  WHERE key = 'catalog_admin_user_id';
$$;

CREATE OR REPLACE FUNCTION public.is_catalog_admin(p_uid uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  SELECT p_uid IS NOT NULL AND p_uid = public.catalog_admin_user_id();
$$;

CREATE OR REPLACE FUNCTION public.is_service_role_caller()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  -- Local PostgREST has no Kong JWT gate; the API/harvester are trusted callers.
  SELECT true;
$$;

CREATE OR REPLACE FUNCTION public.can_write_property(p_property_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  SELECT public.is_service_role_caller()
    OR (
      EXISTS (
        SELECT 1
        FROM public.properties p
        WHERE p.id = p_property_id
      )
    );
$$;

CREATE OR REPLACE FUNCTION public.set_catalog_admin_user_id(p_uid uuid)
RETURNS uuid
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
  IF p_uid IS NULL THEN
    RAISE EXCEPTION 'catalog admin user id required';
  END IF;
  INSERT INTO public.app_runtime_config (key, value)
  VALUES ('catalog_admin_user_id', p_uid::text)
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
  RETURN p_uid;
END;
$$;

CREATE OR REPLACE FUNCTION public.save_property_comps(
  p_property_id uuid,
  p_comps_analysis jsonb,
  p_predicted_value numeric DEFAULT NULL,
  p_prediction_reasoning text DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_comp jsonb;
  v_idx integer := 0;
BEGIN
  IF p_property_id IS NULL OR p_comps_analysis IS NULL THEN
    RETURN false;
  END IF;

  IF NOT public.can_write_property(p_property_id) THEN
    RETURN false;
  END IF;

  UPDATE public.properties
  SET
    comps_analysis = p_comps_analysis,
    predicted_value = COALESCE(p_predicted_value, predicted_value),
    prediction_reasoning = COALESCE(p_prediction_reasoning, prediction_reasoning)
  WHERE id = p_property_id;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  DELETE FROM public.property_comparables WHERE property_id = p_property_id;

  FOR v_comp IN
    SELECT value
    FROM jsonb_array_elements(COALESCE(p_comps_analysis->'comparable_properties', '[]'::jsonb))
  LOOP
    INSERT INTO public.property_comparables (
      property_id,
      sort_order,
      address,
      sale_price,
      sale_date,
      square_footage,
      bedrooms,
      bathrooms,
      distance_miles,
      comparison_notes
    ) VALUES (
      p_property_id,
      v_idx,
      v_comp->>'address',
      NULLIF(v_comp->>'sale_price', '')::numeric,
      v_comp->>'sale_date',
      NULLIF(v_comp->>'square_footage', '')::numeric,
      v_comp->>'bedrooms',
      v_comp->>'bathrooms',
      v_comp->>'distance_miles',
      v_comp->>'comparison_notes'
    );
    v_idx := v_idx + 1;
  END LOOP;

  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.save_property_rent_comps(
  p_property_id uuid,
  p_rent_comps_analysis jsonb,
  p_rent numeric DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
BEGIN
  IF p_property_id IS NULL OR p_rent_comps_analysis IS NULL THEN
    RETURN false;
  END IF;

  IF NOT public.can_write_property(p_property_id) THEN
    RETURN false;
  END IF;

  UPDATE public.properties
  SET
    rent_comps_analysis = p_rent_comps_analysis,
    rent = COALESCE(p_rent, rent)
  WHERE id = p_property_id;

  RETURN FOUND;
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
      view_count, discord_alert_sent_at, archived_at
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
      p.listing_status, p.days_on_market, p.view_count, p.discord_alert_sent_at, now()
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
  DELETE FROM public.properties WHERE timestamp < v_cutoff;
  RETURN v_moved;
END;
$$;
