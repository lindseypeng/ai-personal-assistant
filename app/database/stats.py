"""Read-only queries on listings_clean, shared by the web pages and the chat tools.

Every function takes the same filters, so the prices page, the map, and the
chat always agree on which listings they count.
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import text

from database.connection import SessionLocal


class Filters(BaseModel):
    """Optional filters. Leave a field empty to not filter on it."""

    min_rooms: Optional[float] = Field(None, description="At least this many rooms, for example 2")
    max_rooms: Optional[float] = Field(None, description="At most this many rooms, for example 2.5")
    min_size: Optional[float] = Field(None, description="At least this many square meters")
    max_size: Optional[float] = Field(None, description="At most this many square meters")
    min_price: Optional[float] = Field(None, description="Cold rent of at least this many EUR per month")
    max_price: Optional[float] = Field(None, description="Cold rent of at most this many EUR per month")
    district: Optional[str] = Field(None, description="Berlin district, for example Neukölln")

    def where(self) -> tuple[str, dict]:
        """SQL conditions and their parameters. Values always go in as parameters, never as text."""
        checks = {
            "min_rooms": "rooms >= :min_rooms",
            "max_rooms": "rooms <= :max_rooms",
            "min_size": "size_sqm >= :min_size",
            "max_size": "size_sqm <= :max_size",
            "min_price": "price >= :min_price",
            "max_price": "price <= :max_price",
            "district": "district ILIKE :district",
        }
        params = {name: value for name, value in self.model_dump().items() if value not in (None, "")}
        conditions = [checks[name] for name in params] or ["TRUE"]
        return " AND ".join(conditions), params


LISTING_COLUMNS = "title, price, size_sqm, rooms, price_per_sqm, district, location, move_in_date, link"


def _rows(sql: str, params: dict) -> list[dict]:
    """Run a query and return plain dicts. Postgres numerics become floats, so results are JSON-ready."""
    with SessionLocal() as db:
        return [
            {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            for row in db.execute(text(sql), params).mappings()
        ]


def price_distribution(filters: Filters, bucket_width: int = 100) -> dict:
    """Count, quartiles, and a histogram of monthly rent in buckets of bucket_width EUR."""
    where, params = filters.where()
    summary = _rows(
        f"""
        SELECT count(*) AS count,
               min(price) AS min,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY price) AS p25,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS median,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY price) AS p75,
               max(price) AS max,
               avg(price) AS mean,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_sqm) AS median_per_sqm
        FROM listings_clean WHERE {where}
        """,
        params,
    )[0]
    buckets = _rows(
        f"""
        SELECT floor(price / :width) * :width AS start, count(*) AS count
        FROM listings_clean WHERE {where}
        GROUP BY 1 ORDER BY 1
        """,
        {**params, "width": bucket_width},
    )
    # Fill empty buckets, so the histogram has no hidden gaps
    counts = {int(b["start"]): b["count"] for b in buckets}
    histogram = []
    if counts:
        for start in range(min(counts), max(counts) + bucket_width, bucket_width):
            histogram.append({"from": start, "to": start + bucket_width, "count": counts.get(start, 0)})
    rounded = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in summary.items()}
    return {"currency": "EUR", "bucket_width": bucket_width, **rounded, "histogram": histogram}


def price_extremes(filters: Filters, limit: int = 3) -> dict:
    """The cheapest and the most expensive listings that match the filters."""
    where, params = filters.where()
    params = {**params, "limit": limit}
    sql = f"SELECT {LISTING_COLUMNS} FROM listings_clean WHERE {where} ORDER BY price {{}}, id LIMIT :limit"
    return {
        "cheapest": _rows(sql.format("ASC"), params),
        "most_expensive": _rows(sql.format("DESC"), params),
    }


def districts() -> list[dict]:
    """Every district with its number of listings, largest first."""
    return _rows(
        "SELECT district, count(*) AS count FROM listings_clean "
        "WHERE district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1",
        {},
    )


def map_points(filters: Filters) -> list[dict]:
    """Listings with coordinates. Precision is "address" or "area" (district center only)."""
    where, params = filters.where()
    return _rows(
        f"""
        SELECT {LISTING_COLUMNS}, g.lat, g.lon, g.precision
        FROM listings_clean c JOIN geocodes g USING (location)
        WHERE g.lat IS NOT NULL AND {where}
        """,
        params,
    )


def district_summary(filters: Filters, min_listings: int = 5) -> list[dict]:
    """Per district: number of listings, median rent, and median rent per m², cheapest first.

    Districts with fewer than min_listings listings are left out, since their medians say little.
    """
    where, params = filters.where()
    return _rows(
        f"""
        SELECT district,
               count(*) AS count,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS median_rent,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_sqm))::numeric, 2) AS median_rent_per_sqm
        FROM listings_clean
        WHERE district IS NOT NULL AND {where}
        GROUP BY district
        HAVING count(*) >= :min_listings
        ORDER BY median_rent_per_sqm, district
        """,
        {**params, "min_listings": min_listings},
    )


def search(query: str, filters: Filters, limit: int = 5) -> list[dict]:
    """Listings closest in meaning to the query, for example "bright flat with balcony near a park"."""
    from database.embedding import create_embedding  # needs OPENAI_API_KEY, so import only when used

    where, params = filters.where()
    # <#> is negative inner product: smaller means more similar (OpenAI embeddings have length 1)
    return _rows(
        f"""
        SELECT {LISTING_COLUMNS}
        FROM listings_clean
        WHERE {where}
        ORDER BY embedding <#> CAST(:query_embedding AS vector)
        LIMIT :limit
        """,
        {**params, "query_embedding": str(create_embedding(query)), "limit": limit},
    )
