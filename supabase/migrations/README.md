# Supabase migrations

CapEigen does not run migrations automatically on Streamlit Cloud or local dev. Apply SQL files **manually** in the [Supabase SQL Editor](https://supabase.com/dashboard) (required on the free tier).

## Listing media (Phase 4)

File: `20260613_listing_media.sql`

Adds columns used when the harvester saves scraper-enriched listings:

| Column | Type | Purpose |
|--------|------|---------|
| `primary_image_url` | `text` | Hero/thumbnail URL |
| `image_urls` | `jsonb` | Gallery URLs (JSON array) |
| `days_on_market` | `integer` | DOM from portal |
| `view_count` | `integer` | Listing views (nullable) |
| `listing_status` | `text` | e.g. For Sale, Pending |
| `listing_url` | `text` | Source portal URL |

After applying, confirm with:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'properties'
  AND column_name IN (
    'primary_image_url', 'image_urls', 'days_on_market',
    'view_count', 'listing_status', 'listing_url'
  );
```
