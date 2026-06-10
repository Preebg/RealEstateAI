-- Security hardening: RLS, guest share scope, RPC ownership checks.
-- Applied via Supabase MCP / dashboard. Safe to re-run (idempotent drops).

-- ---------------------------------------------------------------------------
-- Helper: catalog admin (matches existing properties SELECT policy)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.catalog_admin_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  SELECT '7dcc6cb8-8f1d-40cb-ac83-57caae22956a'::uuid;
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
  SELECT coalesce(
    current_setting('request.jwt.claims', true)::jsonb ->> 'role',
    ''
  ) = 'service_role';
$$;

CREATE OR REPLACE FUNCTION public.can_write_property(p_property_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path TO 'public'
AS $$
  SELECT
    public.is_service_role_caller()
    OR (
      auth.uid() IS NOT NULL
      AND EXISTS (
        SELECT 1
        FROM public.properties p
        WHERE p.id = p_property_id
          AND (
            p.user_id = auth.uid()
            OR p.user_id = public.catalog_admin_user_id()
          )
      )
    );
$$;

-- ---------------------------------------------------------------------------
-- properties: remove permissive ALL policy (anon could delete/update entire KB)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS "Enable insert/update for all users" ON public.properties;

-- Shared catalog writes (rows owned by catalog admin UID)
DROP POLICY IF EXISTS "Authenticated insert shared catalog" ON public.properties;
CREATE POLICY "Authenticated insert shared catalog"
  ON public.properties
  FOR INSERT
  TO authenticated
  WITH CHECK (user_id = public.catalog_admin_user_id());

DROP POLICY IF EXISTS "Authenticated update shared catalog" ON public.properties;
CREATE POLICY "Authenticated update shared catalog"
  ON public.properties
  FOR UPDATE
  TO authenticated
  USING (user_id = public.catalog_admin_user_id())
  WITH CHECK (user_id = public.catalog_admin_user_id());

-- Admin may delete catalog rows (harvester purge UI uses authenticated admin JWT)
DROP POLICY IF EXISTS "Catalog admin delete properties" ON public.properties;
CREATE POLICY "Catalog admin delete properties"
  ON public.properties
  FOR DELETE
  TO authenticated
  USING (public.is_catalog_admin(auth.uid()));

-- Drop legacy 5-arg overload after unified 6-arg function is created below
DROP FUNCTION IF EXISTS public.save_share_comps_snapshot(
  text, uuid, jsonb, numeric, text
);

-- ---------------------------------------------------------------------------
-- Guest share: scope portfolio to the shared property only
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_guest_portfolio(p_share_token text)
RETURNS SETOF properties
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
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
$function$;

-- ---------------------------------------------------------------------------
-- Guest property: only the shared listing (no IDOR via p_property_id / address)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_guest_property(
  p_share_token text,
  p_property_id uuid DEFAULT NULL::uuid,
  p_address text DEFAULT NULL::text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
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
$function$;

-- ---------------------------------------------------------------------------
-- Comps RPCs: require ownership (or service role for harvester)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.save_property_comps(
  p_property_id uuid,
  p_comps_analysis jsonb,
  p_predicted_value numeric DEFAULT NULL::numeric,
  p_prediction_reasoning text DEFAULT NULL::text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
  v_comp jsonb;
  v_idx integer := 0;
BEGIN
  IF auth.uid() IS NULL AND NOT public.is_service_role_caller() THEN
    RETURN false;
  END IF;

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
$function$;

CREATE OR REPLACE FUNCTION public.save_property_rent_comps(
  p_property_id uuid,
  p_rent_comps_analysis jsonb,
  p_rent numeric DEFAULT NULL::numeric
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
BEGIN
  IF auth.uid() IS NULL AND NOT public.is_service_role_caller() THEN
    RETURN false;
  END IF;

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
$function$;

-- Share comps snapshot: property must match the share row
CREATE OR REPLACE FUNCTION public.save_share_comps_snapshot(
  p_share_token text,
  p_property_id uuid,
  p_comps_analysis jsonb DEFAULT NULL::jsonb,
  p_predicted_value numeric DEFAULT NULL::numeric,
  p_prediction_reasoning text DEFAULT NULL::text,
  p_rent_comps_analysis jsonb DEFAULT NULL::jsonb
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
  v_share public.property_shares%ROWTYPE;
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN false;
  END IF;

  IF p_comps_analysis IS NULL AND p_rent_comps_analysis IS NULL THEN
    RETURN false;
  END IF;

  SELECT * INTO v_share
  FROM public.property_shares
  WHERE share_token = p_share_token
    AND created_by = auth.uid();

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
$function$;

-- Cron digest: not callable by anon/authenticated clients
REVOKE EXECUTE ON FUNCTION public.invoke_weekly_turnkey_digest() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.invoke_weekly_turnkey_digest() FROM anon;
REVOKE EXECUTE ON FUNCTION public.invoke_weekly_turnkey_digest() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.invoke_weekly_turnkey_digest() TO service_role;

-- Internal trigger helper: not a public API
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM authenticated;
