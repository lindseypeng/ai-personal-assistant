"""Public transport travel times in Berlin, from the free BVG timetable API.

v6.bvg.transport.rest is a community-run wrapper around BVG's own timetable
(https://v6.bvg.transport.rest). It is free and needs no key, but it is rate
limited and has no uptime guarantee, so we only ask it about a short list of
trips, and remember answers for an hour.
"""

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

BVG_URL = "https://v6.bvg.transport.rest/journeys"
USER_AGENT = "ai-personal-assistant-listing-map/0.1"
BERLIN = ZoneInfo("Europe/Berlin")
PARALLEL_REQUESTS = 4  # gentle on a free service
CACHE_SECONDS = 3600

_cache: dict[tuple, tuple[float, dict]] = {}


def default_departure() -> datetime:
    """The next weekday at 8:00 in Berlin: a normal morning commute."""
    day = datetime.now(BERLIN) + timedelta(days=1)
    while day.weekday() >= 5:  # Saturday or Sunday
        day += timedelta(days=1)
    return day.replace(hour=8, minute=0, second=0, microsecond=0)


def parse_departure(text: Optional[str]) -> datetime:
    """None means the default commute, "now" means now, otherwise an ISO time such as 2026-11-16T08:30."""
    if not text:
        return default_departure()
    if text.strip().lower() == "now":
        return datetime.now(BERLIN)
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=BERLIN)


def journey(from_lat: float, from_lon: float, to_lat: float, to_lon: float, departure: datetime) -> dict:
    """The fastest of the next few connections, door to door, including walking."""
    key = (round(from_lat, 5), round(from_lon, 5), round(to_lat, 5), round(to_lon, 5), departure.isoformat())
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    params = urllib.parse.urlencode(
        {
            "from.latitude": from_lat, "from.longitude": from_lon, "from.address": "Start",
            "to.latitude": to_lat, "to.longitude": to_lon, "to.address": "Destination",
            "departure": departure.isoformat(), "results": 3,
            "stopovers": "false", "remarks": "false", "polylines": "false",
        }
    )
    request = urllib.request.Request(f"{BVG_URL}?{params}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            journeys = json.load(response).get("journeys", [])
    except Exception as error:  # timeout, rate limit, service down: report it instead of failing the whole answer
        return {"minutes": None, "error": f"BVG timetable not reachable: {error}"}

    best = None
    for option in journeys:
        legs = option["legs"]
        start = datetime.fromisoformat(legs[0]["departure"])
        end = datetime.fromisoformat(legs[-1]["arrival"])
        minutes = round((end - start).total_seconds() / 60)
        if best is None or minutes < best["minutes"]:
            lines = [leg["line"]["name"] for leg in legs if leg.get("line")]
            best = {
                "minutes": minutes,
                "transfers": max(len(lines) - 1, 0),
                "route": " → ".join(lines) if lines else "walk only",
                "leaves": start.strftime("%H:%M"),
            }
    result = best or {"minutes": None, "error": "No connection found"}
    _cache[key] = (time.monotonic(), result)
    return result


def journeys_to(target_lat: float, target_lon: float, starts: list[tuple[float, float]], departure: datetime) -> list[dict]:
    """Travel times from several starts to one target, a few requests at a time."""
    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        return list(pool.map(lambda s: journey(s[0], s[1], target_lat, target_lon, departure), starts))
