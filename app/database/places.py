"""Places to measure listings against: any named place, and the Berlin S-Bahn Ring.

Distances are straight lines ("as the crow flies"), not travel times.
"""

import math
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.connection import SessionLocal
from database.geocode import geocode
from database.models import GeocodeModel

DEFAULT_PLACE = "Alexanderplatz"

# The 27 Ringbahn stations in order around the Ring, from OpenStreetMap (Nominatim, November 2026).
# Joined in order they outline the area "inside the Ring", the usual Berlin meaning of central.
RING_STATIONS = [
    ("Westkreuz", 52.50169, 13.28156),
    ("Messe Nord/ICC", 52.50633, 13.28335),
    ("Westend", 52.51878, 13.28421),
    ("Jungfernheide", 52.53114, 13.30111),
    ("Beusselstraße", 52.53419, 13.32816),
    ("Westhafen", 52.53627, 13.34430),
    ("Wedding", 52.54279, 13.36700),
    ("Gesundbrunnen", 52.54917, 13.39008),
    ("Schönhauser Allee", 52.54946, 13.41339),
    ("Prenzlauer Allee", 52.54507, 13.42759),
    ("Greifswalder Straße", 52.54073, 13.43828),
    ("Landsberger Allee", 52.52865, 13.45667),
    ("Storkower Straße", 52.52442, 13.46639),
    ("Frankfurter Allee", 52.51488, 13.47463),
    ("Ostkreuz", 52.50247, 13.46851),
    ("Treptower Park", 52.49198, 13.46247),
    ("Sonnenallee", 52.47366, 13.45565),
    ("Neukölln", 52.46973, 13.44441),
    ("Hermannstraße", 52.46763, 13.43124),
    ("Tempelhof", 52.47097, 13.38445),
    ("Südkreuz", 52.47622, 13.36404),
    ("Schöneberg", 52.48004, 13.35255),
    ("Innsbrucker Platz", 52.47811, 13.34323),
    ("Bundesplatz", 52.47783, 13.32859),
    ("Heidelberger Platz", 52.47916, 13.31144),
    ("Hohenzollerndamm", 52.48819, 13.30293),
    ("Halensee", 52.49725, 13.29063),
]


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance on the Earth's surface (haversine formula)."""
    r = 6371.0  # Earth radius in km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def inside_ring(lat: float, lon: float) -> bool:
    """Is the point inside the S-Bahn Ring? Ray casting: count how often a line to the east crosses the Ring."""
    inside = False
    points = [(la, lo) for _, la, lo in RING_STATIONS]
    for (lat_a, lon_a), (lat_b, lon_b) in zip(points, points[1:] + points[:1]):
        if (lat_a > lat) != (lat_b > lat):
            crossing_lon = lon_a + (lat - lat_a) * (lon_b - lon_a) / (lat_b - lat_a)
            if lon < crossing_lon:
                inside = not inside
    return inside


def find_place(name: Optional[str]) -> dict:
    """Coordinates for a place name such as "Alexanderplatz" or "Torstraße 1".

    Looked up with Nominatim once and then read from the geocodes table.
    Raises ValueError when the place cannot be found.
    """
    name = (name or DEFAULT_PLACE).strip()
    key = f"place:{name.lower()}"  # kept apart from listing locations in the same table
    with SessionLocal() as db:
        row = db.scalars(select(GeocodeModel).where(GeocodeModel.location == key)).first()
    if row is None:
        found = geocode(name)
        with SessionLocal() as db:
            db.execute(insert(GeocodeModel).values({**found, "location": key}).on_conflict_do_nothing())
            db.commit()
        lat, lon = found["lat"], found["lon"]
    else:
        lat, lon = row.lat, row.lon
    if lat is None:
        raise ValueError(f"Could not find the place {name!r} in Berlin. Try a street address or a station name.")
    return {"name": name, "lat": lat, "lon": lon, "inside_ring": inside_ring(lat, lon)}
