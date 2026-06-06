-- Harvester + underwriter fields missing from public.properties
-- Run after 002_hitl_telemetry.sql

ALTER TABLE public.properties
  ADD COLUMN IF NOT EXISTS square_footage numeric,
  ADD COLUMN IF NOT EXISTS property_condition text,
  ADD COLUMN IF NOT EXISTS property_category text,
  ADD COLUMN IF NOT EXISTS from_kb boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS appreciation_forecast numeric,
  ADD COLUMN IF NOT EXISTS forecast_rate numeric,
  ADD COLUMN IF NOT EXISTS forecast_growth numeric,
  ADD COLUMN IF NOT EXISTS ai_vacancy_rate numeric,
  ADD COLUMN IF NOT EXISTS ai_management_fee numeric,
  ADD COLUMN IF NOT EXISTS monthly_net_cash_flow numeric;

COMMENT ON COLUMN public.properties.square_footage IS 'Living area in square feet';
COMMENT ON COLUMN public.properties.property_condition IS 'Excellent | Good | Fair | Poor';
COMMENT ON COLUMN public.properties.property_category IS 'Strategy/branding label (often mirrors property_label)';
COMMENT ON COLUMN public.properties.from_kb IS 'True when row was saved to or loaded from the knowledge base';
COMMENT ON COLUMN public.properties.appreciation_forecast IS 'Projected property value at end of 10-year horizon';
COMMENT ON COLUMN public.properties.forecast_rate IS 'Projected annual appreciation rate (percent)';
COMMENT ON COLUMN public.properties.forecast_growth IS 'Total projected growth over forecast horizon (percent)';
COMMENT ON COLUMN public.properties.ai_vacancy_rate IS 'AI-suggested vacancy reserve rate (percent of rent)';
COMMENT ON COLUMN public.properties.ai_management_fee IS 'AI-suggested property management fee (percent of rent)';
COMMENT ON COLUMN public.properties.monthly_net_cash_flow IS 'Net monthly cash flow at save time (harvester/underwriter)';
