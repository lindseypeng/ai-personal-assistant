"""Turn listing locations into map coordinates with Nominatim (OpenStreetMap).

Nominatim is free but allows at most 1 request per second, so every result is
stored in the geocodes table and each location is looked up only once.
Run it by hand to fill the table: cd app && uv run database/geocode.py
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing database

from database.connection import SessionLocal
from database.models import GeocodeModel

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy asks every app to identify itself
USER_AGENT = "ai-personal-assistant-listing-map/0.1"
SECONDS_BETWEEN_REQUESTS = 1.1

# Nominatim result types that mean "a whole district", not a building or street
AREA_TYPES = {"suburb", "quarter", "city_district", "neighbourhood", "borough", "city", "town", "village"}

_last_request = 0.0


def clean_location(location: str) -> str:
    """'Donaustraße 42c, Neukölln (Ortsteil), Berlin' -> 'Donaustraße 42c, Neukölln, Berlin'"""
    location = re.sub(r"\(.*?\)", "", location)
    location = re.sub(r"(\w)-\s+", r"\1-", location)  # "Caroline- Michaelis- Straße"
    return re.sub(r"\s+", " ", location).replace(" ,", ",").strip(" ,")


def search(query: str) -> Optional[dict]:
    """One Nominatim lookup in Germany, waiting first so we never exceed the rate limit."""
    global _last_request
    wait = SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "de"})
    request = urllib.request.Request(f"{NOMINATIM_URL}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            results = json.load(response)
    finally:
        _last_request = time.monotonic()
    return results[0] if results else None


def geocode(location: str) -> dict:
    """Try the full address first, then only the district, so most listings get a pin."""
    query = clean_location(location)
    if "berlin" not in query.lower():
        query += ", Berlin"
    result = search(query)
    if result is None and query.count(",") >= 2:
        # Drop the street: "Unknown Str. 1, Karow, Berlin" -> "Karow, Berlin"
        result = search(query.split(",", 1)[1].strip())
    if result is None:
        return {"location": location, "lat": None, "lon": None, "precision": "none"}
    precision = "area" if result.get("addresstype") in AREA_TYPES else "address"
    return {"location": location, "lat": float(result["lat"]), "lon": float(result["lon"]), "precision": precision}


def missing_locations() -> list[str]:
    """Locations of clean listings that have not been looked up yet."""
    statement = text(
        """
        SELECT DISTINCT c.location
        FROM listings_clean c
        LEFT JOIN geocodes g ON g.location = c.location
        WHERE c.location IS NOT NULL AND g.location IS NULL
        """
    )
    with SessionLocal() as db:
        return list(db.scalars(statement))


def geocode_missing(verbose: bool = False) -> int:
    """Look up every new location and store it. Returns how many were stored."""
    locations = missing_locations()
    for number, location in enumerate(locations, start=1):
        try:
            row = geocode(location)
        except Exception as error:  # network trouble: skip it, the next run tries again
            print(f"Geocoding failed for {location!r}: {error}")
            continue
        with SessionLocal() as db:
            db.execute(insert(GeocodeModel).values(row).on_conflict_do_nothing())
            db.commit()
        if verbose:
            print(f"{number}/{len(locations)} {row['precision']:7} {location}", flush=True)
    return len(locations)


if __name__ == "__main__":
    print(f"Geocoded {geocode_missing(verbose=True)} locations")
