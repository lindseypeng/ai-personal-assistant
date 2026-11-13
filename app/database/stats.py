"""Read-only queries on listings_clean, shared by the web pages and the chat tools.

Every function takes the same filters, so the prices page, the map, and the
chat always agree on which listings they count.
"""

import re
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


def buildings_with_multiple_listings(
    filters: Filters,
    wanted_rooms: Optional[list[float]] = None,
    seen_within_days: Optional[int] = None,
    exclude_wbs: bool = False,
    limit: int = 10,
    near_place: Optional[str] = None,
    max_km: Optional[float] = None,
    inside_ring_only: bool = False,
) -> dict:
    """Buildings with several listings at once, for example one 1-room and one 2-room flat.

    Listings are grouped by map coordinates, not by address text, because the same
    building is often written differently ("Moissistraße 31" and "Moissistraße +31+").
    Only listings with a street address count; district-only listings have no building.
    Each wanted room count n matches n to n + 0.5 rooms, and every one must be offered.
    With near_place, each building gets its straight-line distance and results are sorted by it.
    """
    from database.places import distance_km, find_place, inside_ring

    target = find_place(near_place) if near_place else None
    where, params = filters.where()
    if seen_within_days is not None:
        where += " AND c.email_date >= now() - make_interval(days => :days)"
        params = {**params, "days": seen_within_days}
    if exclude_wbs:
        where += r" AND coalesce(c.title, '') !~ '\mWBS\M'"
    rows = _rows(
        f"""
        SELECT {LISTING_COLUMNS}, c.email_date::date AS seen_on, g.lat, g.lon
        FROM listings_clean c JOIN geocodes g USING (location)
        WHERE g.precision = 'address' AND {where}
        ORDER BY c.price
        """,
        params,
    )

    # About 1 meter apart at most: the same building
    buildings: dict[tuple, list[dict]] = {}
    for row in rows:
        buildings.setdefault((round(row["lat"], 5), round(row["lon"], 5)), []).append(row)

    found = []
    for (lat, lon), listings in buildings.items():
        if len(listings) < 2:
            continue
        if wanted_rooms and not all(
            any(r["rooms"] is not None and n <= r["rooms"] <= n + 0.5 for r in listings) for n in wanted_rooms
        ):
            continue
        building_inside_ring = inside_ring(lat, lon)
        if inside_ring_only and not building_inside_ring:
            continue
        distance = round(distance_km(target["lat"], target["lon"], lat, lon), 2) if target else None
        if max_km is not None and distance is not None and distance > max_km:
            continue
        # The most common spelling of the address, the shortest on a tie
        names = [r["location"] for r in listings]
        address = min(set(names), key=lambda name: (-names.count(name), len(name)))
        found.append(
            {
                "address": address,
                "district": listings[0]["district"],
                "lat": lat,
                "lon": lon,
                "inside_ring": building_inside_ring,
                "distance_km": distance,
                "listing_count": len(listings),
                "rooms_offered": sorted({r["rooms"] for r in listings if r["rooms"] is not None}),
                "listings": [
                    {
                        **{k: r[k] for k in ("title", "rooms", "size_sqm", "price", "seen_on", "link")},
                        # WBS: social housing, only with a housing permit (Wohnberechtigungsschein)
                        "needs_wbs": bool(re.search(r"\bWBS\b", r["title"] or "")),
                    }
                    for r in listings
                ],
            }
        )

    if target:
        found.sort(key=lambda b: b["distance_km"])
    else:
        found.sort(key=lambda b: (-len(b["rooms_offered"]), -b["listing_count"], b["listings"][0]["price"]))
    return {"place": target, "buildings_found": len(found), "buildings": found[:limit]}


def listings_near_place(
    filters: Filters,
    place: Optional[str] = None,
    max_km: Optional[float] = None,
    inside_ring_only: bool = False,
    limit: int = 10,
) -> dict:
    """Listings closest to a place, with straight-line distance and whether they are inside the S-Bahn Ring.

    Only listings with a street address count; district-only listings have no exact position.
    """
    from database.places import distance_km, find_place, inside_ring

    target = find_place(place)
    where, params = filters.where()
    rows = _rows(
        f"""
        SELECT {LISTING_COLUMNS}, c.email_date::date AS seen_on, g.lat, g.lon
        FROM listings_clean c JOIN geocodes g USING (location)
        WHERE g.precision = 'address' AND {where}
        """,
        params,
    )
    for row in rows:
        row["distance_km"] = round(distance_km(target["lat"], target["lon"], row["lat"], row["lon"]), 2)
        row["inside_ring"] = inside_ring(row["lat"], row["lon"])
    rows = [
        r for r in rows
        if (max_km is None or r["distance_km"] <= max_km) and (not inside_ring_only or r["inside_ring"])
    ]
    rows.sort(key=lambda r: r["distance_km"])
    return {"place": target, "listings_found": len(rows), "listings": rows[:limit]}


def transit_times(
    filters: Filters,
    place: Optional[str] = None,
    addresses: Optional[list[str]] = None,
    candidates: int = 8,
    max_km: Optional[float] = None,
    inside_ring_only: bool = False,
    departure: Optional[str] = None,
) -> dict:
    """Public transport minutes to a place, for given addresses or for the nearest listings.

    Without addresses, the nearest listings by straight line are the shortlist, so a farther
    listing next to a fast train line can be missed; raise candidates to look further.
    """
    from database.places import find_place
    from database.transit import journeys_to, parse_departure

    target = find_place(place)
    leave_at = parse_departure(departure)

    if addresses:
        starts = []
        for address in addresses:
            with SessionLocal() as db:
                row = db.execute(
                    text("SELECT lat, lon FROM geocodes WHERE location = :a AND lat IS NOT NULL"), {"a": address}
                ).first()
            if row:
                starts.append({"address": address, "lat": row.lat, "lon": row.lon})
            else:
                found = find_place(address)  # raises ValueError if unknown
                starts.append({"address": address, "lat": found["lat"], "lon": found["lon"]})
    else:
        starts = listings_near_place(filters, place, max_km, inside_ring_only, limit=candidates)["listings"]

    trips = journeys_to(target["lat"], target["lon"], [(s["lat"], s["lon"]) for s in starts], leave_at)
    results = []
    for start, trip in zip(starts, trips):
        item = {k: v for k, v in start.items() if k not in ("lat", "lon")}
        results.append({**item, **{f"transit_{k}" if k != "error" else "transit_error": v for k, v in trip.items()}})
    results.sort(key=lambda r: (r.get("transit_minutes") is None, r.get("transit_minutes") or 0))
    return {
        "place": target,
        "departure": leave_at.strftime("%A %Y-%m-%d %H:%M"),
        "source": "BVG timetable (v6.bvg.transport.rest), door to door including walking",
        "results": results,
    }
