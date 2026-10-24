import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing database

from database.connection import Base, engine
from database.models import ListingModel  # noqa: F401  registers the table


def create_tables() -> None:
    """Enable pgvector and create every table defined in database/models.py."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # create_all only adds missing tables, it never changes existing ones
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    create_tables()
    print("Tables:", ", ".join(Base.metadata.tables))
