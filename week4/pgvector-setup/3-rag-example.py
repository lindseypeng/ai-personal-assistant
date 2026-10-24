"""
RAG: Retrieval, then Generation

Scripts 1 and 2 stop at retrieval: they return the closest rows and you read them.
This script adds generation, the same two steps as POST /ask in the app:
- Retrieve: rank the listings in practice_listings by similarity to the question
- Generate: give those listings to an LLM and let it answer using only them

Run 1-basic-operations.py first. It creates and fills the practice_listings table.
"""

import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector
from pydantic import BaseModel, Field

from listings import DATABASE_URL, get_embeddings

PROMPT = """
You help the user find an apartment. Answer the user's question using only the numbered listings below.
Cite the numbers of the listings your answer relies on.
If no listing fits the question, say so plainly and cite nothing. Do not invent listings or details.
"""


class GroundedAnswer(BaseModel):
    answer: str = Field(description="Answer to the question, based only on the listings")
    cited_numbers: list[int] = Field(description="Numbers of the listings the answer relies on")


def retrieve(question: str, limit: int = 3) -> list[str]:
    """R: the same similarity search as script 1. No LLM writes anything here."""
    query_embedding = get_embeddings([question])[0]
    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        rows = conn.execute(
            """
            SELECT content FROM practice_listings
            ORDER BY embedding <#> %s::vector
            LIMIT %s
            """,
            (query_embedding, limit),
        ).fetchall()
    return [content for (content,) in rows]


def generate(question: str, listings: list[str]) -> GroundedAnswer:
    """G: one LLM call that answers from the retrieved listings only."""
    context = "\n".join(f"[{n}] {listing}" for n, listing in enumerate(listings, start=1))
    response = OpenAI().responses.parse(
        model="gpt-4o-mini",
        # Retrieved listings go in the instructions, the question alone is the user input
        instructions=f"{PROMPT}\nListings:\n{context}",
        input=question,
        text_format=GroundedAnswer,
    )
    return response.output_parsed


def ask(question: str):
    print(f"\nQuestion: {question}")

    listings = retrieve(question)
    print("Retrieved (what search alone gives you):")
    for n, listing in enumerate(listings, start=1):
        print(f"  [{n}] {listing}")

    result = generate(question, listings)
    print(f"Generated answer: {result.answer}")
    print(f"Cited: {result.cited_numbers}")


def main():
    ask("Which flat would suit a student on a budget?")
    ask("I have a dog. Is there anything with outdoor space?")
    # Nothing matches, so a grounded answer should say so instead of inventing a listing
    ask("Is there a castle with a moat?")


if __name__ == "__main__":
    main()
