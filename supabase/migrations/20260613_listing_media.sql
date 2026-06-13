-- Listing media + scraper metadata for properties (Phase 4).
--
-- MANUAL APPLY REQUIRED (Supabase free tier):
--   1. Supabase Dashboard -> SQL Editor -> New query
--   2. Paste this file and Run
--   3. Verify columns on public.properties before running harvester saves
--
-- Safe to re-run: uses IF NOT EXISTS for each column.

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS primary_image_url text;

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS image_urls jsonb;

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS days_on_market integer;

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS view_count integer;

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS listing_status text;

ALTER TABLE public.properties
    ADD COLUMN IF NOT EXISTS listing_url text;
