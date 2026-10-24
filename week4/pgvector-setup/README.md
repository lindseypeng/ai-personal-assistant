# Postgres and pgvector Practice

Two small scripts that store apartment listings in Postgres and search them by meaning. Run them before looking at the app code in `app/database/`, which uses the same ideas.

## What Is pgvector?

An **embedding** is a list of numbers (here 1536) that represents the meaning of a piece of text. Texts with similar meanings get similar lists, so "garden flat with terrace" lands close to "Wohnung mit Terrasse und Gartenzugang", even though they share no words.

**pgvector** is a Postgres extension that adds a `vector` column type and operators to compare vectors. That means one database can hold both the normal listing data (price, rooms, location) and its embedding, and a single SQL query can filter by price and rank by meaning.

| Operator | Measures | Use it when |
|----------|----------|-------------|
| `<#>` | Negative inner product | Vectors are normalized, like OpenAI embeddings. This is what we use. |
| `<=>` | Cosine distance | Vectors are not normalized |
| `<->` | Euclidean (L2) distance | The actual distance matters |

For OpenAI embeddings, inner product and cosine give the same ranking, and inner product is faster. `<#>` returns the *negative* inner product so that `ORDER BY` puts the best match first. The scripts flip the sign to print a similarity where higher means more similar.

## Setup

1. **Install packages** from the project root: `uv sync`
2. **Check `.env`** has `OPENAI_API_KEY` and `DATABASE_URL`. See `.env.example`.
3. **Start Postgres** from the project root:

   ```bash
   docker compose up -d
   ```

   This runs the `pgvector/pgvector:pg17` image, which is Postgres 17 with pgvector already installed. Data is kept in a Docker volume, so it survives restarts. `docker compose down -v` deletes it.

4. **Check it is running:** `docker exec -it assistant-pgvector-db psql -U postgres -c "SELECT version();"`

**Port 5432 already in use?** Another Postgres is running, often from a different project. Stop it, or run this one on another port: set `POSTGRES_PORT=5434` and change `DATABASE_URL` to use `localhost:5434`.

## Which Listings Are Used?

`listings.py` loads `requests/apartments.csv` if you created one with the apartment workflow. Otherwise it loads `sample_listings.csv`, 16 made-up Berlin listings. Your own CSV stays out of Git because it holds content from your emails.

## Run the Scripts

Run both from this folder:

```bash
cd week4/pgvector-setup
uv run 1-basic-operations.py
uv run 2-sqlalchemy-example.py
```

Each run drops and recreates its own practice table, so you can run them as often as you like. They do not touch the app's `listings` table.

### 1. Basic Operations (plain SQL)

`1-basic-operations.py` uses `psycopg` and writes every SQL statement by hand:

1. `CREATE EXTENSION vector` turns on pgvector
2. `CREATE TABLE` with an `embedding vector(1536)` column
3. `CREATE INDEX ... USING hnsw (embedding vector_ip_ops)` for fast search
4. `INSERT` each listing with its embedding
5. `ORDER BY embedding <#> query_vector` to rank by meaning, with an optional `WHERE price <= ...`

### 2. SQLAlchemy

`2-sqlalchemy-example.py` does the same with the SQLAlchemy ORM, the style the app uses. The table is a Python class with a `Vector(1536)` column, and search uses `.max_inner_product()` instead of writing `<#>` by hand. It also shows how to stack normal filters (`max_price`, `min_rooms`) on top of a similarity search.

## Things to Try

- **Compare the two datasets.** The sample listings have titles such as "Garden flat with private terrace". A CSV from the Week 3 workflow has no title column, so the embedded text is only location, rooms, size, and price. Run the same query on both and compare the similarity scores. The text you embed decides what search can find.
- **Search in another language.** Ask in English and see whether German listings still match.
- **Change the filters.** What happens to the ranking when `min_rooms=3` removes the best match?
- **Read the SQL.** Add `echo=True` to `create_engine` in the SQLAlchemy script to print the queries it sends.

## HNSW or IVFFlat?

pgvector has two index types:

- **HNSW** (what we use) builds a graph of nearby vectors. It finds good matches reliably at any table size. Building it is slower and uses more memory.
- **IVFFlat** groups vectors into clusters and searches only the closest ones. It builds faster, but on small tables it can return fewer results than you asked for unless you lower `lists`.

For a few hundred listings, Postgres may skip the index and scan every row, which is still fast. The index matters once you have many thousands of rows.
