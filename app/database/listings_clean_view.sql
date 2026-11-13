-- listings_clean: the cleaned listings that the MCP tools read from.
-- A view, not a table, so it stays current as the pipeline adds listings.
--
-- Rules:
-- 1. Rentals only: price between 150 and 2000 EUR. No listing is priced
--    between 2000 and 50000, so anything higher is a sale. Below 150 are
--    extraction errors (1 EUR). Listings without a price are left out.
-- 2. Currency: every value is EUR, "€" or empty, so all become EUR.
-- 3. Deduplication: one row per ImmoScout expose ID from the link
--    (tracking parameters differ per email). Links without an ID fall back
--    to title + location. The most recent email wins.
-- 4. District: locations look like "Street 1, Friedrichshain, Berlin", so the
--    district is the part before "Berlin", without notes in brackets.

DROP VIEW IF EXISTS public.listings_clean;

CREATE VIEW public.listings_clean
WITH (security_invoker = true) AS
WITH keyed AS (
    SELECT
        l.*,
        string_to_array(l.location, ',') AS parts,
        substring(l.link FROM 'expose/(\d+)') AS expose_id,
        coalesce(
            substring(l.link FROM 'expose/(\d+)'),
            'title:' || md5(coalesce(l.title, '') || '|' || coalesce(l.location, ''))
        ) AS dedup_key
    FROM public.listings l
    WHERE l.price BETWEEN 150 AND 2000
),
ranked AS (
    SELECT
        k.*,
        row_number() OVER (PARTITION BY k.dedup_key ORDER BY k.email_date DESC, k.id DESC) AS rn
    FROM keyed k
)
SELECT
    id,
    expose_id,
    title,
    price,
    'EUR'::text AS currency,
    size_sqm,
    rooms,
    CASE WHEN size_sqm > 0 THEN round((price / size_sqm)::numeric, 2) END AS price_per_sqm,
    location,
    nullif(trim(regexp_replace(
        CASE
            WHEN cardinality(parts) >= 2 AND trim(parts[cardinality(parts)]) ILIKE 'berlin%'
                THEN parts[cardinality(parts) - 1]
            ELSE parts[cardinality(parts)]
        END,
        '\(.*?\)', '', 'g'
    )), '') AS district,
    move_in_date,
    CASE
        WHEN expose_id IS NOT NULL THEN 'https://www.immobilienscout24.de/expose/' || expose_id
        ELSE link
    END AS link,
    to_timestamp(email_date) AS email_date,
    created_at,
    content,
    embedding
FROM ranked
WHERE rn = 1;

-- security_invoker makes the view respect RLS on listings. Also keep it out
-- of the public Supabase REST API, like the table itself.
REVOKE ALL ON public.listings_clean FROM anon, authenticated;
