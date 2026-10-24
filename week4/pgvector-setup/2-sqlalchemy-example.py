"""
SQLAlchemy Integration with pgvector

The same listing search as 1-basic-operations.py, written with the SQLAlchemy ORM.
This is the style the app uses in app/database/. It shows how to:
- Define a model with a Vector column and an HNSW index
- Insert rows as Python objects
- Search with .max_inner_product() instead of writing <#> by hand
- Add normal filters (price, rooms) to a similarity search
"""

from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Float, Index, Integer, Text, create_engine, select, text
from sqlalchemy.orm import Session, declarative_base

from listings import DATABASE_URL, EMBEDDING_DIMENSIONS, get_embeddings, listing_text, load_listings

# "postgresql+psycopg" tells SQLAlchemy to use the psycopg 3 driver
engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1))
Base = declarative_base()


class PracticeListing(Base):
    __tablename__ = "practice_listings_orm"
    __table_args__ = (
        Index(
            "ix_practice_listings_orm_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_ip_ops"},
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    price = Column(Float)
    rooms = Column(Float)
    size_sqm = Column(Float)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS))


def create_tables():
    """Drop and recreate the table so each run starts clean."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def insert_listings():
    listings = load_listings()
    texts = [listing_text(listing) for listing in listings]
    embeddings = get_embeddings(texts)

    with Session(engine) as session:
        session.add_all(
            PracticeListing(
                content=content,
                price=listing["price"],
                rooms=listing["rooms"],
                size_sqm=listing["size_sqm"],
                embedding=embedding,
            )
            for listing, content, embedding in zip(listings, texts, embeddings)
        )
        session.commit()
    print(f"Inserted {len(listings)} listings")


def search(
    query: str,
    limit: int = 3,
    max_price: Optional[float] = None,
    min_rooms: Optional[float] = None,
):
    """Filter with normal SQL first, then rank what is left by meaning."""
    print(f"\nSearch: '{query}' (max_price={max_price}, min_rooms={min_rooms})")
    query_embedding = get_embeddings([query])[0]
    distance = PracticeListing.embedding.max_inner_product(query_embedding)

    statement = select(PracticeListing, distance.label("distance"))
    if max_price is not None:
        statement = statement.where(PracticeListing.price <= max_price)
    if min_rooms is not None:
        statement = statement.where(PracticeListing.rooms >= min_rooms)
    statement = statement.order_by(distance).limit(limit)

    with Session(engine) as session:
        for listing, dist in session.execute(statement):
            print(f"  {-dist:.3f}  {listing.content}")


def main():
    create_tables()
    insert_listings()

    search("bright flat with outdoor space")
    search("bright flat with outdoor space", min_rooms=3)
    search("good for a student on a budget", max_price=1000)


if __name__ == "__main__":
    main()
