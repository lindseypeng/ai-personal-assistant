from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from database.connection import Base

EMBEDDING_DIMENSIONS = 1536


class ListingModel(Base):
    """One apartment listing from an email, with its embedding for semantic search."""

    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("email_id", "listing_number", name="uq_listings_email_listing"),
        # HNSW index for fast similarity search. Inner product works because
        # OpenAI embeddings are normalized to length 1.
        Index(
            "ix_listings_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_ip_ops"},
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Where the listing came from
    email_id = Column(String, nullable=False)
    listing_number = Column(Integer, nullable=False)
    email_date = Column(BigInteger, nullable=False)  # Unix timestamp
    subject = Column(String, nullable=True)

    # Details extracted by the LLM, same fields as schemas.listing_schema.Listing
    title = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    location = Column(Text, nullable=True)
    size_sqm = Column(Float, nullable=True)
    rooms = Column(Float, nullable=True)
    move_in_date = Column(String, nullable=True)
    link = Column(Text, nullable=True)

    # The text we embedded, and its embedding
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
