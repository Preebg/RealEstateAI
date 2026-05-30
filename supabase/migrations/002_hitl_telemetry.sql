-- Human-in-the-loop telemetry on properties (expert overrides vs AI baselines)
ALTER TABLE public.properties
  ADD COLUMN IF NOT EXISTS original_ai_rent numeric,
  ADD COLUMN IF NOT EXISTS original_ai_maint numeric,
  ADD COLUMN IF NOT EXISTS is_outlier boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS override_notes text;

COMMENT ON COLUMN public.properties.original_ai_rent IS 'AI-suggested monthly rent at analysis time';
COMMENT ON COLUMN public.properties.original_ai_maint IS 'AI-suggested maintenance % at analysis time';
COMMENT ON COLUMN public.properties.is_outlier IS 'True when user rent deviates >50% from original_ai_rent';
COMMENT ON COLUMN public.properties.override_notes IS 'Expert explanation when is_outlier is true';
