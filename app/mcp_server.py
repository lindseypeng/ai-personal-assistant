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


def http_app():
    """The MCP endpoint as an ASGI app, mounted at /mcp in main.py.

    Locally the app has no password, so the SDK's localhost-only host check stays on
    (it blocks DNS rebinding from websites). On Cloud Run APP_PASSWORD protects /mcp,
    and the host is the run.app domain, so the check is turned off there.
    """
    host = "0.0.0.0" if os.environ.get("APP_PASSWORD") else "127.0.0.1"
    return mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True, host=host)
