from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.connection import SessionLocal
from database.embedding import create_embedding
from database.models import ListingModel
from schemas.listing_schema import Listing, ListingSearchResult, listing_to_text
from schemas.nylas_email_schema import EmailObject


def save_listings(email: EmailObject, listings: list[Listing]) -> int:
    """Embed and store each listing. Listings already stored for this email are skipped."""
    with SessionLocal() as db:
        stored = set(
            db.scalars(
                select(ListingModel.listing_number).where(ListingModel.email_id == email.id)
            )
        )
        rows = []
        for number, listing in enumerate(listings, start=1):
            if number in stored:
                continue
            content = listing_to_text(listing)
            rows.append(
                {
                    "email_id": email.id,
                    "listing_number": number,
                    "email_date": email.date,
                    "subject": email.subject,
                    **listing.model_dump(),
                    "content": content,
                    "embedding": create_embedding(content),
                }
            )
        if rows:
            db.execute(insert(ListingModel).values(rows).on_conflict_do_nothing())
            db.commit()
    return len(rows)


def search_listings(
    query: str,
    limit: int = 5,
    max_price: Optional[float] = None,
    min_rooms: Optional[float] = None,
) -> list[ListingSearchResult]:
    """Rank listings by meaning, after normal SQL filters on price and rooms."""
    # <#> is negative inner product, so smaller distance means more similar
    distance = ListingModel.embedding.max_inner_product(create_embedding(query))
    statement = select(ListingModel, distance.label("distance"))
    if max_price is not None:
        statement = statement.where(ListingModel.price <= max_price)
    if min_rooms is not None:
        statement = statement.where(ListingModel.rooms >= min_rooms)
    statement = statement.order_by(distance).limit(limit)

    with SessionLocal() as db:
        return [
            ListingSearchResult(
                **Listing.model_validate(row, from_attributes=True).model_dump(),
                email_id=row.email_id,
                similarity=-dist,
            )
            for row, dist in db.execute(statement)
        ]
