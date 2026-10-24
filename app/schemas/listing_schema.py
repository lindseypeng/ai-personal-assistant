from typing import Optional

from pydantic import BaseModel, Field


class Listing(BaseModel):
    title: Optional[str] = Field(description="Listing headline as written in the email")
    price: Optional[float] = Field(description="Rent or sale price as a number")
    currency: Optional[str] = Field(description="Currency code, for example EUR")
    location: Optional[str] = Field(description="City, district or address")
    size_sqm: Optional[float] = Field(description="Size in square meters")
    rooms: Optional[float] = Field(description="Number of rooms")
    move_in_date: Optional[str] = Field(description="Available from, as written")
    link: Optional[str] = Field(description="URL to the listing")


class ListingSearchResult(Listing):
    email_id: str
    similarity: float


def listing_to_text(listing: Listing) -> str:
    """Describe a listing in one line of text, the input we embed for semantic search."""
    parts = [
        listing.title,
        listing.location,
        f"{listing.rooms:g} rooms" if listing.rooms else None,
        f"{listing.size_sqm:g} sqm" if listing.size_sqm else None,
        f"{listing.price:.0f} {listing.currency or ''}".strip() if listing.price else None,
        f"available from {listing.move_in_date}" if listing.move_in_date else None,
    ]
    return ". ".join(p for p in parts if p)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    limit: int = Field(5, ge=1, le=20)
    max_price: Optional[float] = None
    min_rooms: Optional[float] = None


class AskResponse(BaseModel):
    answer: str
    sources: list[ListingSearchResult]
