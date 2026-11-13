"""MCP server with read-only tools on the clean Berlin rental listings.

The website's chat uses these tools, and any MCP client can too, for example
Claude Desktop or Claude Code, at <app url>/mcp/ with the app password.
Every tool calls database/stats.py, so the chat and the web pages give the same numbers.
"""

import os
from typing import Annotated, Optional

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from database import stats

mcp = MCPServer(
    "berlin-listings",
    instructions=(
        "Tools on Berlin rental listings from ImmoScout24 search alerts. Prices are monthly cold rent "
        "in EUR. Sales, listings without a price, and duplicates are already removed."
    ),
)

# The same optional filters on every tool. Leave one out to not filter on it.
MinRooms = Annotated[Optional[float], Field(description="At least this many rooms, for example 2")]
MaxRooms = Annotated[Optional[float], Field(description="At most this many rooms. For exactly 2 rooms use min 2 and max 2.5")]
MinSize = Annotated[Optional[float], Field(description="At least this many square meters")]
MaxSize = Annotated[Optional[float], Field(description="At most this many square meters")]
MinPrice = Annotated[Optional[float], Field(description="Monthly cold rent of at least this many EUR")]
MaxPrice = Annotated[Optional[float], Field(description="Monthly cold rent of at most this many EUR")]
NearPlace = Annotated[Optional[str], Field(description="A Berlin place, station, or street address, for example Alexanderplatz or Torstraße 1")]
MaxKm = Annotated[Optional[float], Field(gt=0, description="At most this many km in a straight line from the place")]
InsideRingOnly = Annotated[bool, Field(description="Only listings inside the S-Bahn Ring, the usual meaning of central Berlin")]
District = Annotated[Optional[str], Field(description="One Berlin district, spelled as in compare_districts, for example Neukölln")]


@mcp.tool()
def price_distribution(
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
) -> dict:
    """How rents are spread: count, min, quartiles, median, max, mean, median rent per m², and a histogram in 100 EUR bands."""
    return stats.price_distribution(stats.Filters(**locals()))


@mcp.tool()
def cheapest_and_most_expensive(
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
    limit: Annotated[int, Field(ge=1, le=10, description="How many listings at each end")] = 3,
) -> dict:
    """The cheapest and the most expensive listings, with title, rent, size, rooms, district, and link."""
    args = dict(locals())
    del args["limit"]
    return stats.price_extremes(stats.Filters(**args), limit=limit)


@mcp.tool()
def compare_districts(
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    min_listings: Annotated[int, Field(ge=1, description="Leave out districts with fewer listings")] = 5,
) -> list[dict]:
    """Every district with its number of listings, median rent, and median rent per m², cheapest per m² first.

    Also use it to find the exact spelling of a district.
    """
    args = dict(locals())
    del args["min_listings"]
    return stats.district_summary(stats.Filters(**args), min_listings=min_listings)


@mcp.tool()
def search_listings(
    query: Annotated[str, Field(description="What the person wants, in words, for example 'quiet flat with balcony'")],
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
    limit: Annotated[int, Field(ge=1, le=20, description="How many listings to return")] = 5,
) -> list[dict]:
    """Find listings by meaning (semantic search), after the filters. Use it for wishes like features or style."""
    args = dict(locals())
    del args["query"], args["limit"]
    return stats.search(query, stats.Filters(**args), limit=limit)


@mcp.tool()
def find_buildings_with_multiple_listings(
    wanted_rooms: Annotated[
        Optional[list[float]],
        Field(description="Room counts that must all be offered in the same building, for example [1, 2] "
                          "for a 1-room and a 2-room flat. Each number n also matches n + 0.5. "
                          "Leave out for any building with 2 or more listings"),
    ] = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
    seen_within_days: Annotated[Optional[int], Field(ge=1, description="Only listings first seen in the last N days")] = None,
    exclude_wbs: Annotated[bool, Field(description="Leave out listings that need a WBS (social housing permit)")] = False,
    near_place: NearPlace = None,
    max_km: MaxKm = None,
    inside_ring_only: InsideRingOnly = False,
    limit: Annotated[int, Field(ge=1, le=20, description="How many buildings to return")] = 5,
) -> dict:
    """Buildings that offer several flats at the same time, for example a 1-room and a 2-room flat at one address.

    Listings are grouped by map position, so different spellings of one address count as one building.
    Only listings with a street address count. Each listing says whether it needs a WBS (social housing permit).
    The filters apply to each listing. With near_place, buildings are sorted by straight-line distance to it.
    """
    filters = stats.Filters(min_size=min_size, max_size=max_size, min_price=min_price, max_price=max_price, district=district)
    try:
        return stats.buildings_with_multiple_listings(
            filters, wanted_rooms, seen_within_days, exclude_wbs, limit, near_place, max_km, inside_ring_only
        )
    except ValueError as error:  # the place was not found: tell the agent, so it can ask the user
        return {"error": str(error)}


@mcp.tool()
def listings_near_place(
    place: Annotated[Optional[str], Field(description="A Berlin place, station, or street address. Defaults to Alexanderplatz")] = None,
    max_km: MaxKm = None,
    inside_ring_only: InsideRingOnly = False,
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
    limit: Annotated[int, Field(ge=1, le=20, description="How many listings to return")] = 10,
) -> dict:
    """Listings closest to a place, nearest first, with straight-line distance in km and whether each is inside the S-Bahn Ring.

    Distances are as the crow flies, not travel time. Only listings with a street address count.
    """
    args = dict(locals())
    for name in ("place", "max_km", "inside_ring_only", "limit"):
        del args[name]
    try:
        return stats.listings_near_place(stats.Filters(**args), place, max_km, inside_ring_only, limit)
    except ValueError as error:  # the place was not found: tell the agent, so it can ask the user
        return {"error": str(error)}


@mcp.tool()
def transit_time_to_place(
    place: Annotated[Optional[str], Field(description="Where the person needs to get to: a Berlin place, station, or street address. Defaults to Alexanderplatz")] = None,
    addresses: Annotated[
        Optional[list[str]],
        Field(description="Addresses to check, exactly as other tools returned them, for example the buildings from "
                          "find_buildings_with_multiple_listings. Leave out to check the listings nearest to the place"),
    ] = None,
    departure: Annotated[Optional[str], Field(description="When to leave: 'now' or an ISO time like 2026-11-16T08:30. Defaults to the next weekday at 08:00")] = None,
    candidates: Annotated[int, Field(ge=1, le=20, description="Without addresses: how many of the nearest listings to check")] = 8,
    max_km: MaxKm = None,
    inside_ring_only: InsideRingOnly = False,
    min_rooms: MinRooms = None, max_rooms: MaxRooms = None,
    min_size: MinSize = None, max_size: MaxSize = None,
    min_price: MinPrice = None, max_price: MaxPrice = None,
    district: District = None,
) -> dict:
    """Real public transport travel time (BVG timetable, door to door, including walking) to a place, fastest first.

    Checks either the given addresses, or the nearest listings that match the filters.
    Each result has the minutes, the number of transfers, and the lines, for example "U8 → S5".
    """
    filters = stats.Filters(
        min_rooms=min_rooms, max_rooms=max_rooms, min_size=min_size, max_size=max_size,
        min_price=min_price, max_price=max_price, district=district,
    )
    try:
        return stats.transit_times(filters, place, addresses, candidates, max_km, inside_ring_only, departure)
    except ValueError as error:  # unknown place or address, or a bad departure time
        return {"error": str(error)}


def http_app():
    """The MCP endpoint as an ASGI app, mounted at /mcp in main.py.

    Locally the app has no password, so the SDK's localhost-only host check stays on
    (it blocks DNS rebinding from websites). On Cloud Run APP_PASSWORD protects /mcp,
    and the host is the run.app domain, so the check is turned off there.
    """
    host = "0.0.0.0" if os.environ.get("APP_PASSWORD") else "127.0.0.1"
    return mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True, host=host)
