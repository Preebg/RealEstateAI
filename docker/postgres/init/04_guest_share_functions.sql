-- Guest share RPCs used by FastAPI. Safe on local PostgREST (no auth.uid()).
-- Also applied to existing volumes by scripts/migrate_supabase_to_local.py.

CREATE OR REPLACE FUNCTION public.is_valid_share_token(p_token text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.property_shares
    WHERE share_token = p_token
      AND (expires_at IS NULL OR expires_at > now())
  );
$$;

CREATE OR REPLACE FUNCTION public.validate_share_token(p_token text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_share public.property_shares%ROWTYPE;
  v_address text;
BEGIN
  SELECT * INTO v_share FROM public.property_shares
  WHERE share_token = p_token
    AND (expires_at IS NULL OR expires_at > now());

  IF NOT FOUND THEN
    RETURN jsonb_build_object('valid', false);
  END IF;

  SELECT address INTO v_address FROM public.properties WHERE id = v_share.property_id;

  RETURN jsonb_build_object(
    'valid', true,
    'property_id', v_share.property_id,
    'address', v_address,
    'include_assumptions', v_share.include_assumptions,
    'expires_at', v_share.expires_at
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.get_guest_portfolio(p_share_token text)
RETURNS SETOF properties
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_share public.property_shares%ROWTYPE;
BEGIN
  SELECT * INTO v_share
  FROM public.property_shares
  WHERE share_token = p_share_token
    AND (expires_at IS NULL OR expires_at > now());

  IF NOT FOUND THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT p.*
  FROM public.properties p
  WHERE p.id = v_share.property_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_guest_property(
  p_share_token text,
  p_property_id uuid DEFAULT NULL,
  p_address text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_share public.property_shares%ROWTYPE;
  v_prop public.properties%ROWTYPE;
  v_override public.user_property_overrides%ROWTYPE;
  v_share_comps public.property_share_comps%ROWTYPE;
  v_result jsonb;
BEGIN
  SELECT * INTO v_share FROM public.property_shares
  WHERE share_token = p_share_token
    AND (expires_at IS NULL OR expires_at > now());

  IF NOT FOUND THEN
    RETURN jsonb_build_object('valid', false);
  END IF;

  SELECT * INTO v_prop FROM public.properties WHERE id = v_share.property_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('valid', true, 'property', null);
  END IF;

  IF p_property_id IS NOT NULL AND p_property_id <> v_share.property_id THEN
    RETURN jsonb_build_object('valid', false);
  END IF;

  IF p_address IS NOT NULL AND btrim(p_address) <> '' THEN
    IF lower(btrim(v_prop.address)) <> lower(btrim(p_address)) THEN
      RETURN jsonb_build_object('valid', false);
    END IF;
  END IF;

  SELECT * INTO v_share_comps
  FROM public.property_share_comps
  WHERE share_token = p_share_token;

  SELECT to_jsonb(v_prop) INTO v_result;

  IF v_share_comps.comps_analysis IS NOT NULL THEN
    v_result := v_result || jsonb_build_object(
      'comps_analysis', v_share_comps.comps_analysis
    );
    IF v_share_comps.predicted_value IS NOT NULL THEN
      v_result := v_result || jsonb_build_object(
        'predicted_value', v_share_comps.predicted_value
      );
    END IF;
    IF v_share_comps.prediction_reasoning IS NOT NULL THEN
      v_result := v_result || jsonb_build_object(
        'prediction_reasoning', v_share_comps.prediction_reasoning
      );
    END IF;
  END IF;

  IF v_share_comps.rent_comps_analysis IS NOT NULL THEN
    v_result := v_result || jsonb_build_object(
      'rent_comps_analysis', v_share_comps.rent_comps_analysis
    );
  END IF;

  IF v_share.include_assumptions THEN
    SELECT * INTO v_override FROM public.user_property_overrides
    WHERE user_id = v_share.created_by AND property_id = v_prop.id;
    IF FOUND THEN
      v_result := v_result
        || jsonb_build_object(
          'rent', v_override.rent,
          'maint_percent', v_override.maint_percent,
          'user_vacancy_rate', v_override.vacancy_rate,
          'user_management_fee', v_override.management_fee,
          'is_outlier', v_override.is_outlier,
          'override_notes', v_override.override_notes,
          'has_user_override', true
        );
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'valid', true,
    'property_id', v_share.property_id,
    'include_assumptions', v_share.include_assumptions,
    'property', v_result
  );
END;
$$;

-- Local PostgREST is a trusted caller (FastAPI already authenticated the user).
CREATE OR REPLACE FUNCTION public.save_share_comps_snapshot(
  p_share_token text,
  p_property_id uuid,
  p_comps_analysis jsonb DEFAULT NULL,
  p_predicted_value numeric DEFAULT NULL,
  p_prediction_reasoning text DEFAULT NULL,
  p_rent_comps_analysis jsonb DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_share public.property_shares%ROWTYPE;
BEGIN
  IF p_comps_analysis IS NULL AND p_rent_comps_analysis IS NULL THEN
    RETURN false;
  END IF;

  SELECT * INTO v_share
  FROM public.property_shares
  WHERE share_token = p_share_token;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  IF p_property_id IS DISTINCT FROM v_share.property_id THEN
    RETURN false;
  END IF;

  INSERT INTO public.property_share_comps (
    share_token,
    property_id,
    comps_analysis,
    predicted_value,
    prediction_reasoning,
    rent_comps_analysis
  ) VALUES (
    p_share_token,
    p_property_id,
    p_comps_analysis,
    p_predicted_value,
    p_prediction_reasoning,
    p_rent_comps_analysis
  )
  ON CONFLICT (share_token) DO UPDATE SET
    property_id = EXCLUDED.property_id,
    comps_analysis = COALESCE(EXCLUDED.comps_analysis, property_share_comps.comps_analysis),
    predicted_value = COALESCE(EXCLUDED.predicted_value, property_share_comps.predicted_value),
    prediction_reasoning = COALESCE(
      EXCLUDED.prediction_reasoning,
      property_share_comps.prediction_reasoning
    ),
    rent_comps_analysis = COALESCE(
      EXCLUDED.rent_comps_analysis,
      property_share_comps.rent_comps_analysis
    ),
    created_at = now();

  RETURN true;
END;
$$;

GRANT EXECUTE ON FUNCTION public.is_valid_share_token(text) TO capeigen_app;
GRANT EXECUTE ON FUNCTION public.validate_share_token(text) TO capeigen_app;
GRANT EXECUTE ON FUNCTION public.get_guest_portfolio(text) TO capeigen_app;
GRANT EXECUTE ON FUNCTION public.get_guest_property(text, uuid, text) TO capeigen_app;
GRANT EXECUTE ON FUNCTION public.save_share_comps_snapshot(text, uuid, jsonb, numeric, text, jsonb) TO capeigen_app;
