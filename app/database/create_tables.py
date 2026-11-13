import sys
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing database

from database.connection import Base, engine
from database.models import GeocodeModel, ListingModel  # noqa: F401  registers the tables

VIEW_SQL = Path(__file__).with_name("listings_clean_view.sql")


def create_tables() -> None:
    """Enable pgvector, create every table in database/models.py, and the listings_clean view."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    # create_all only adds missing tables, it never changes existing ones
    Base.metadata.create_all(bind=engine)
    # Supabase serves tables in "public" through its web API. Row level security with
    # no policies blocks that API, while the app's own connection keeps full access.
    with engine.begin() as conn:
        for table in Base.metadata.tables:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        # Send the file through psycopg directly, without parameters, so "%" and ":"
        # in the SQL are not mistaken for placeholders
        conn.connection.driver_connection.execute(VIEW_SQL.read_text())


if __name__ == "__main__":
    create_tables()
    print("Tables:", ", ".join(Base.metadata.tables), "+ view listings_clean")
