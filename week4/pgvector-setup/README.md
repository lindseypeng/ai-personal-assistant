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

## The Data

`sample_listings.csv` holds 16 simulated Berlin listings. I made them up to mimic the listings my own project extracts from real apartment alert emails, with the same columns, so no personal email content is needed.

## The RAG Pipeline in These Scripts

| Step | Where it happens |
|------|------------------|
| Document processing | `listings.py` loads the CSV and `listing_text` turns each listing into one line of text. There is no chunking: each listing is about 30 tokens, so one listing is already one chunk. |
| Embedding generation | `get_embeddings` in `listings.py`, with `text-embedding-3-small`, used by scripts 1, 2, and 3 |
| Vector storage | Script 1 (`1-basic-operations.py`, plain SQL) and script 2 (`2-sqlalchemy-example.py`, SQLAlchemy) insert each listing with its embedding |
| Similarity search | `search` in scripts 1 and 2, `retrieve` in script 3 (`3-rag-example.py`) |
| Response generation | `generate` in script 3 only |

Chunking matters for long text such as articles or PDFs, which are split into pieces before embedding so each vector covers one topic. Short records like listings are embedded whole.

## Run the Scripts

Run them in order from this folder:

```bash
cd week4/pgvector-setup
uv run 1-basic-operations.py
uv run 2-sqlalchemy-example.py
uv run 3-rag-example.py
```

Scripts 1 and 2 drop and recreate their own practice tables, so you can run them as often as you like. Script 3 reads the table from script 1. None of them touch the app's `listings` table.

### 1. Basic Operations (plain SQL)

`1-basic-operations.py` uses `psycopg` and writes every SQL statement by hand:

1. `CREATE EXTENSION vector` turns on pgvector
2. `CREATE TABLE` with an `embedding vector(1536)` column
3. `CREATE INDEX ... USING hnsw (embedding vector_ip_ops)` for fast search
4. `INSERT` each listing with its embedding
5. `ORDER BY embedding <#> query_vector` to rank by meaning, with an optional `WHERE price <= ...`

### 2. SQLAlchemy

`2-sqlalchemy-example.py` does the same with the SQLAlchemy ORM, the style the app uses. The table is a Python class with a `Vector(1536)` column, and search uses `.max_inner_product()` instead of writing `<#>` by hand. It also shows how to stack normal filters (`max_price`, `min_rooms`) on top of a similarity search.

Scripts 1 and 2 are retrieval only. The queries read like questions, but each one is embedded and compared with the stored vectors, and you get back the closest rows. No LLM writes an answer.

### 3. RAG: Retrieval, then Generation

`3-rag-example.py` adds the generation step, the same two steps as `POST /ask` in the app:

1. **Retrieve:** rank the listings by similarity to the question, as in script 1.
2. **Generate:** number the retrieved listings, put them in the prompt, and let `gpt-4o-mini` answer using only those listings and cite the numbers it used.

It prints the retrieved listings and the generated answer one after the other, so you can see what each step adds. The last question, "Is there a castle with a moat?", shows a grounded answer saying nothing fits instead of inventing a listing.

## Things to Try

- **Remove the titles.** Change `listing_text` to leave out `listing["title"]`, run script 1 again, and compare the similarity scores. The text you embed decides what search can find.
- **Search in another language.** Ask in German, for example "Wohnung mit Garten", and see whether the English listings still match.
- **Change what the LLM sees.** In script 3, retrieve only 1 listing instead of 3. Retrieval limits what generation can answer.
- **Change the filters.** What happens to the ranking when `min_rooms=3` removes the best match?
- **Read the SQL.** Add `echo=True` to `create_engine` in the SQLAlchemy script to print the queries it sends.

## HNSW or IVFFlat?

pgvector has two index types:

- **HNSW** (what we use) builds a graph of nearby vectors. It finds good matches reliably at any table size. Building it is slower and uses more memory.
- **IVFFlat** groups vectors into clusters and searches only the closest ones. It builds faster, but on small tables it can return fewer results than you asked for unless you lower `lists`.

For a few hundred listings, Postgres may skip the index and scan every row, which is still fast. The index matters once you have many thousands of rows.
