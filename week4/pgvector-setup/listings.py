"""
Shared helpers for the Week 4 practice scripts.

Loads the simulated apartment listings in sample_listings.csv and turns each one
into text we can embed.
"""

import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SAMPLE_CSV = Path(__file__).resolve().parent / "sample_listings.csv"

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def to_number(value: str):
    return float(value) if value else None


def load_listings() -> list[dict]:
    with open(SAMPLE_CSV) as f:
        rows = list(csv.DictReader(f))
    return [
        {
            "title": row["title"] or None,
            "location": row["location"] or None,
            "price": to_number(row["price"]),
            "currency": row["currency"] or None,
            "size_sqm": to_number(row["size_sqm"]),
            "rooms": to_number(row["rooms"]),
            "link": row["link"] or None,
        }
        for row in rows
    ]


def listing_text(listing: dict) -> str:
    """One line describing the listing. This is the text we embed."""
    parts = [
        listing["title"],
        listing["location"],
        f"{listing['rooms']:g} rooms" if listing["rooms"] else None,
        f"{listing['size_sqm']:g} sqm" if listing["size_sqm"] else None,
        f"{listing['price']:.0f} {listing['currency'] or ''}".strip() if listing["price"] else None,
    ]
    return ". ".join(p for p in parts if p)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed many texts in one API call. Each text gets a 1536-number vector."""
    response = OpenAI().embeddings.create(
        model=EMBEDDING_MODEL, input=texts, dimensions=EMBEDDING_DIMENSIONS
    )
    return [item.embedding for item in response.data]
