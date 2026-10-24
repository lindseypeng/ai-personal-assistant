import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing schemas and database

from database.repository import search_listings
from schemas.listing_schema import AskResponse, ListingSearchResult, listing_to_text

load_dotenv()

PROMPT = """
You help the user find an apartment. Answer the user's question using only the numbered listings below.
Cite the numbers of the listings your answer relies on.
If no listing fits the question, say so plainly and cite nothing. Do not invent listings or details.
Reply in the language the user writes in, even when the listings are in another language.
"""


class GroundedAnswer(BaseModel):
    answer: str = Field(description="Answer to the question, based only on the listings")
    cited_numbers: list[int] = Field(description="Numbers of the listings the answer relies on")


# --------------------------------------------------------------
# Step 1: Retrieve the most similar listings (the R in RAG)
# --------------------------------------------------------------


def retrieve(
    question: str,
    limit: int = 5,
    max_price: Optional[float] = None,
    min_rooms: Optional[float] = None,
) -> list[ListingSearchResult]:
    return search_listings(question, limit=limit, max_price=max_price, min_rooms=min_rooms)


# --------------------------------------------------------------
# Step 2: Put the listings into the prompt as numbered context
# --------------------------------------------------------------


def build_context(listings: list[ListingSearchResult]) -> str:
    return "\n".join(
        f"[{number}] {listing_to_text(listing)}"
        for number, listing in enumerate(listings, start=1)
    )


# --------------------------------------------------------------
# Step 3: Generate an answer grounded in that context (the G in RAG)
# --------------------------------------------------------------


def generate(question: str, listings: list[ListingSearchResult]) -> GroundedAnswer:
    response = OpenAI().responses.parse(
        model="gpt-4o-mini",
        # Listings go in the instructions and the question alone is the user input,
        # so the LLM keeps the user's language even when the listings are in German
        instructions=f"{PROMPT}\nListings:\n{build_context(listings)}",
        input=question,
        text_format=GroundedAnswer,
    )
    return response.output_parsed


def ask(
    question: str,
    limit: int = 5,
    max_price: Optional[float] = None,
    min_rooms: Optional[float] = None,
) -> AskResponse:
    listings = retrieve(question, limit, max_price, min_rooms)
    if not listings:
        return AskResponse(answer="No saved listings match these filters.", sources=[])

    result = generate(question, listings)
    # Keep only numbers that point to a real listing, in case the LLM cites one that doesn't exist
    sources = [listings[n - 1] for n in result.cited_numbers if 1 <= n <= len(listings)]
    return AskResponse(answer=result.answer, sources=sources)


if __name__ == "__main__":
    response = ask(sys.argv[1])  # the question, in quotes
    print(response.answer)
    print("\nSources:")
    for source in response.sources:
        print(f"- {source.title} ({source.link})")
