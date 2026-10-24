"""
Basic Vector Operations with pgvector

Stores apartment listings and their embeddings in Postgres with plain SQL, then
searches them by meaning. It shows how to:
- Enable the pgvector extension and create a table with a vector column
- Insert listings together with their embeddings
- Rank listings by similarity with the <#> operator
- Combine similarity search with a normal SQL filter
"""

import psycopg
from pgvector.psycopg import register_vector

from listings import DATABASE_URL, EMBEDDING_DIMENSIONS, get_embeddings, listing_text, load_listings


def create_connection():
    """Connect to Postgres and teach psycopg about the vector type."""
    conn = psycopg.connect(DATABASE_URL)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def create_table(conn):
    """Start fresh each run so the script can be run again and again."""
    conn.execute("DROP TABLE IF EXISTS practice_listings")
    conn.execute(
        f"""
        CREATE TABLE practice_listings (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            content TEXT NOT NULL,
            price DOUBLE PRECISION,
            rooms DOUBLE PRECISION,
            link TEXT,
            embedding vector({EMBEDDING_DIMENSIONS})
        )
        """
    )
    # HNSW index for fast similarity search. vector_ip_ops = inner product,
    # which ranks the same as cosine similarity for OpenAI's normalized vectors.
    conn.execute(
        "CREATE INDEX ON practice_listings USING hnsw (embedding vector_ip_ops)"
    )
    conn.commit()


def insert_listings(conn):
    listings = load_listings()
    texts = [listing_text(listing) for listing in listings]
    embeddings = get_embeddings(texts)

    with conn.cursor() as cur:
        for listing, content, embedding in zip(listings, texts, embeddings):
            cur.execute(
                """
                INSERT INTO practice_listings (content, price, rooms, link, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (content, listing["price"], listing["rooms"], listing["link"], embedding),
            )
    conn.commit()
    print(f"Inserted {len(listings)} listings")


def search(conn, query: str, limit: int = 3, max_price: float | None = None):
    """
    <#> returns the negative inner product, so the smallest value is the best match.
    We flip the sign to show a similarity where higher means more similar.
    """
    print(f"\nSearch: '{query}'" + (f" with price <= {max_price:g}" if max_price else ""))
    query_embedding = get_embeddings([query])[0]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content, -(embedding <#> %s::vector) AS similarity
            FROM practice_listings
            WHERE %s::float IS NULL OR price <= %s::float
            ORDER BY embedding <#> %s::vector
            LIMIT %s
            """,
            (query_embedding, max_price, max_price, query_embedding, limit),
        )
        for content, similarity in cur.fetchall():
            print(f"  {similarity:.3f}  {content}")


def main():
    with create_connection() as conn:
        create_table(conn)
        insert_listings(conn)

        search(conn, "somewhere quiet for a family with kids")
        search(conn, "close to public transport")
        search(conn, "close to public transport", max_price=1000)


if __name__ == "__main__":
    main()
