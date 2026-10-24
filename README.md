# Week 4: Postgres and pgvector

## This Week's Goals

1. **Learn vector search:** Store apartment listings in Postgres with pgvector and search them by meaning. Practice with the scripts in [week4/pgvector-setup](week4/pgvector-setup/README.md).
2. **Move the app to Postgres:** The apartment workflow now saves each listing with an embedding in Postgres instead of a CSV file, and `GET /search` finds listings by meaning with optional price and room filters.
3. **Complete RAG:** `/search` is the Retrieval step. `POST /ask` adds Generation: an LLM answers your question using only the retrieved listings and cites the ones it used.

## Before You Start: Recap

This week builds on the [apartment listing workflow](https://github.com/lindseypeng/ai-personal-assistant/blob/apartment-listings/README.md), which classifies each incoming email and extracts its listings with an LLM. Email capture works the same as in [Week 3](https://github.com/lindseypeng/ai-personal-assistant/blob/week-3/README.md): start a Cloudflare tunnel, start `main.py`, and update the webhook. See [Start a New Session](docs/start-new-session.md) for each step.

You need these in `.env` (see `.env.example`):

- `OPENAI_API_KEY` for classification and embeddings
- `DATABASE_URL` for Postgres. The default `postgresql://postgres:postgres@localhost:5432/postgres` matches `docker-compose.yml`.

Then install the new packages (`pgvector`, `sqlalchemy`, `psycopg`) with `uv sync`.

## Week 4 Workflow

```mermaid
flowchart LR
    A[New email] --> B[FastAPI POST /events]
    B --> C[Save event JSON]
    C --> D[LLM classification and extraction]
    D -->|No listings| E[No action]
    D -->|Listings found| F[Describe each listing as text]
    F --> G[OpenAI embedding]
    G --> H[(Postgres listings table)]
    I[GET /search?q=...] --> J[Embed the query]
    J --> K[SQL filters and similarity ranking]
    H --> K
    K --> L[Best matching listings]
    L --> M[LLM answers from those listings]
    M --> N[Answer with cited sources]
```

Each listing is stored as one row with its details (title, price, rooms, size, location, link), the text we embedded, and a 1536-number `embedding` column. Search embeds your question the same way, keeps only rows that pass the price and room filters, and sorts the rest by similarity.

## Part 1: Practice with pgvector

Start Postgres from the project root, then follow the [practice README](week4/pgvector-setup/README.md):

```bash
docker compose up -d
cd week4/pgvector-setup
uv run 1-basic-operations.py
uv run 2-sqlalchemy-example.py
```

The scripts use your own `requests/apartments.csv` if you have one, otherwise a set of made-up sample listings.

## Part 2: Store and Search Listings in the App

**1. Create the table** (safe to run again, it only adds missing tables):

```bash
uv run app/database/create_tables.py
```

**2. Load the emails you already captured.** This runs the apartment workflow on every file in `requests/events/` and stores the listings it finds. Emails already in the database are skipped. Emails without listings are checked again on each run, which costs one LLM call each.

```bash
uv run app/database/load_events.py
```

New emails are stored automatically while `main.py` is running.

**3. Search.** Start the app (`cd app` then `uv run main.py`) and open `http://localhost:8000/docs`, or call the endpoint directly:

```bash
curl "http://localhost:8000/search?q=garden+flat+with+terrace"
curl "http://localhost:8000/search?q=quiet+place+for+a+couple&max_price=800&min_rooms=2&limit=3"
```

| Parameter | Description |
|-----------|-------------|
| `q` | What you are looking for, in any language |
| `limit` | Number of results, 1 to 50, default 5 |
| `max_price` | Only listings at or below this price |
| `min_rooms` | Only listings with at least this many rooms |

Each result has the listing details, the `email_id` it came from, and a `similarity` score where higher means more similar.

## Part 3: Ask Questions with RAG

Search returns the closest listings, but you still read them yourself. RAG (Retrieval-Augmented Generation) adds one more LLM call that reads them for you:

1. **Retrieve:** Run the same search as `/search` to get the top listings.
2. **Augment:** Number the listings (`[1]`, `[2]`, ...) and put them into the LLM's instructions.
3. **Generate:** The LLM answers the question using only those listings, and returns the numbers it relied on. The app turns those numbers back into full listings as `sources`.

The workflow lives in `app/workflows/ask_workflow.py`. Try it from the terminal:

```bash
uv run app/workflows/ask_workflow.py "Which flats would suit a couple on a small budget?"
```

Or with `main.py` running:

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Gibt es eine Wohnung mit Garten?", "max_price": 1500}'
```

The request takes `question`, plus the same `limit`, `max_price`, and `min_rooms` as `/search`. The response has an `answer` and its `sources`.

**Why the answer stays grounded:**

- The prompt tells the LLM to use only the listings given and to say so when none fit. Ask "Is there a castle with a moat?" to see it decline instead of inventing one.
- Citations are numbers, not free text, and any number that doesn't match a retrieved listing is dropped. Every source is a real row from your database.
- If the filters leave no listings, the app answers without calling the LLM at all.

**Where the context goes matters.** The listings are in the instructions and the question alone is the user input. When the German listings and the English question were sent together as one input, the LLM often answered in German. Keeping them apart lets it reply in the user's language.

**Retrieval limits the answer.** The LLM only sees the top `limit` listings. If the best apartment isn't retrieved, the answer can't mention it. Raise `limit` or loosen the filters and compare the answers.

## Code Map

| File | What it does |
|------|--------------|
| `docker-compose.yml` | Runs Postgres 17 with pgvector |
| `app/schemas/listing_schema.py` | `Listing`, `ListingSearchResult`, `AskRequest`, and `AskResponse` models, and `listing_to_text`, which builds the text we embed |
| `app/database/connection.py` | SQLAlchemy engine and sessions |
| `app/database/models.py` | `listings` table with a `Vector(1536)` column and an HNSW index |
| `app/database/embedding.py` | `create_embedding` with `text-embedding-3-small` |
| `app/database/repository.py` | `save_listings` and `search_listings` |
| `app/database/create_tables.py` | Enables pgvector and creates the table |
| `app/database/load_events.py` | Backfills listings from saved events |
| `app/workflows/ask_workflow.py` | RAG: retrieves listings and generates a grounded answer with sources |
| `app/workflows/apartment_workflow.py` | Classifies emails and saves listings to Postgres |

## Things to Know

- **Listings now have a title.** The LLM also extracts each listing's headline, such as "Helle 2-Zimmer-Wohnung mit eigenem Garten". Titles carry most of the meaning, so they make search far better than location and numbers alone.
- **Rent and sale prices share one column.** `max_price=800` also hides every listing for sale. Filter on what you are searching for.
- **The CSV is no longer written.** An old `requests/apartments.csv` is still used by the practice scripts and stays out of Git.
- **Port 5432 already in use?** Another Postgres is running, often from a different project. Stop it, or set `POSTGRES_PORT=5434` in `.env` and use `localhost:5434` in `DATABASE_URL`.
- **`/ask` sends listings to OpenAI.** The retrieved listings and your question go to the LLM on every call.
- **Protect the app before running it long term.** The tunnel makes the whole app public, including `/search` and `/ask`, which return your saved listings.
