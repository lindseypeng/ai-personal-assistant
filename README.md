# Week 6: Deploy the Assistant to Cloud Run and Supabase

## This Week's Goals

1. **Move the database to Supabase:** A hosted Postgres with pgvector replaces the Docker database, so the listings live online.
2. **Run the app on Google Cloud Run:** Cloud Run builds the app from the `Dockerfile` and gives it a fixed HTTPS address, so the webhook no longer depends on a tunnel that changes every session.
3. **Keep it private:** Nylas can reach `/events`. Every other page asks for a password.

This adapts the [Datalumina week 6 deployment guide](https://github.com/datalumina/genai-accelerator-labs/blob/project/ai-assistant-week-6/docs/6-deployment-guide.md). That guide runs everything on one VM with Caddy and self-hosted Supabase. Here Google and Supabase run the servers, so there is no VM, Caddy, or domain to manage.

## How It Fits Together

```mermaid
flowchart LR
    N[Nylas] -->|HTTPS /events| R[Cloud Run: FastAPI main.py]
    U[You, with the password] -->|HTTPS| R
    R --> S[(Supabase Postgres with pgvector)]
```

| File | What it does |
|------|--------------|
| `Dockerfile` | Builds the app. On start it creates the table if missing, then runs `main.py`. |
| `.dockerignore` | Keeps `.env`, saved emails, and local files out of the image |
| `app/main.py` | Listens on Cloud Run's `PORT`, and asks for `APP_PASSWORD` when it is set |
| `cloudrun.env.yaml` | You create it: the settings Cloud Run passes to the app. Ignored by Git. |

Locally nothing changes. Leave `APP_PASSWORD` empty and the app runs without a login on port 8000.

Settings worth knowing:

- **`--no-cpu-throttling`:** the app replies to Nylas first, then classifies the email in the background. Cloud Run normally slows the CPU right after the reply, so this keeps it running until the work is done.
- **`--max-instances 1`:** the main page keeps results in memory, so every request has to reach the same instance.
- **Scale to zero:** after some idle minutes Cloud Run stops the app. The first request afterwards takes a few seconds, and the main page starts empty. Listings stay in Supabase, so `/search` and `/ask` still find them.
- **Saved emails:** the raw event files are written inside the container and disappear when it stops. The extracted listings are what is kept.

## Deploy, Step by Step

### 1. Create the Supabase database

1. Create a project at [supabase.com](https://supabase.com) in **Central EU (Frankfurt)**, close to your Nylas EU region and Cloud Run. Save the database password.
2. Click **Connect** and copy the **Session pooler** connection string. Cloud Run can't reach the direct connection, which needs IPv6.
3. Replace `[YOUR-PASSWORD]` in it with your database password. This is your `DATABASE_URL`.

The app enables pgvector and creates the `listings` table itself when it starts.

### 2. Set up Google Cloud

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### 3. Write the Cloud Run settings

Create `cloudrun.env.yaml` in the repo root with the values from your `.env`:

```yaml
NYLAS_API_KEY: "..."
NYLAS_API_URI: "https://api.eu.nylas.com"
NYLAS_CLIENT_ID: "..."
NYLAS_GRANT_ID: "..."
OPENAI_API_KEY: "..."
DATABASE_URL: "postgresql://postgres.xxxx:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
APP_PASSWORD: "choose a strong password"
WEBHOOK_SECRET: ""
```

`WEBHOOK_SECRET` stays empty until step 5.

### 4. Deploy

From the repo root:

```bash
gcloud run deploy assistant \
  --source . \
  --region europe-west3 \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --max-instances 1 \
  --env-vars-file cloudrun.env.yaml
```

Cloud Build builds the `Dockerfile` and Cloud Run prints the service URL, such as `https://assistant-xxxx.europe-west3.run.app`. Open it, enter any username and your `APP_PASSWORD`, and you see the main page.

`--allow-unauthenticated` lets Nylas reach the app. The password check in `main.py` protects every page except `/events`, and `/events` checks the Nylas signature.

### 5. Create the webhook

On your laptop, set `SERVER_URL` in your local `.env` to the Cloud Run URL, then run `cd app/config` and `uv run config_webhook.py`.

Put the printed secret into `WEBHOOK_SECRET` in `cloudrun.env.yaml`, then load it without rebuilding:

```bash
gcloud run services update assistant --region europe-west3 --env-vars-file cloudrun.env.yaml
```

Delete the old trycloudflare webhook in the Nylas Dashboard, so Nylas stops reporting it as failing.

### 6. Test end to end

Send yourself an apartment listing email, then check:

- The logs show `POST /events 200`: `gcloud run services logs read assistant --region europe-west3`
- The email shows up on the main page with its listings.
- In Supabase, **Table Editor** shows the new rows in `listings`.

### Optional: load emails you captured locally

Run the loader on your laptop against Supabase:

```bash
DATABASE_URL="your Supabase URL" uv run app/database/load_events.py
```

## Day-to-Day

| Task | Command |
|------|---------|
| Deploy new code | The `gcloud run deploy` command from step 4 |
| Change a setting | Edit `cloudrun.env.yaml`, then the `gcloud run services update` command from step 5 |
| Read logs | `gcloud run services logs read assistant --region europe-west3` |
| Run locally again | `docker compose up -d`, then `cd app` and `uv run main.py`, as in Week 4 |

---

# Week 4 Reference: Postgres, pgvector, and RAG

## The Example Data: Apartment Listings

The examples use apartment listings from my own project. It reads apartment alert emails from sites like ImmobilienScout24, and an LLM extracts each listing's title, price, size, rooms, location, and link. One email can hold many listings. The practice scripts use simulated listings that mimic the data from my project, so you don't need it to follow along. The same ideas apply to any data you capture with Nylas.

## Data Schema

Before creating a table, decide what one row represents and which columns it needs. Here, **one row is one listing**, not one email, because we search and cite individual listings.

The fields come from the Pydantic model `Listing` in `app/schemas/listing_schema.py`, the same shape the LLM returns. The table `listings` in `app/database/models.py` stores those fields, plus columns to trace each row back to its email and the columns needed for vector search.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | integer, primary key | Unique row id |
| `email_id` | text | Nylas id of the email the listing came from |
| `listing_number` | integer | Position of the listing in that email. Together with `email_id` it is unique, so re-processing an email adds no duplicates. |
| `email_date` | bigint | When the email arrived, as a Unix timestamp |
| `subject` | text | Email subject |
| `title` | text | Listing headline, for example "Helle 2-Zimmer-Wohnung mit eigenem Garten" |
| `price`, `currency` | float, text | Rent or sale price |
| `location` | text | City, district, or address |
| `size_sqm`, `rooms` | float | Size in square meters and number of rooms |
| `move_in_date` | text | Available from, as written in the email |
| `link` | text | URL to the listing |
| `content` | text | The text we embed, built from the fields above by `listing_to_text` |
| `embedding` | vector(1536) | The embedding of `content` |
| `created_at` | timestamp | When the row was stored |

Design choices worth noticing:

- **Listing fields can be empty.** The LLM leaves out details the email doesn't state, so only the source columns and the embedding are required.
- **Normal columns for filters, a vector for meaning.** `price` and `rooms` are numbers so SQL can filter them exactly. `title` and `location` feed the embedding so search can match by meaning.
- **`content` is stored next to its embedding,** so you can always see which text produced a vector.
- **`vector(1536)` must match the embedding model.** `text-embedding-3-small` returns 1536 numbers.
- **An HNSW index on `embedding`** makes similarity search fast as the table grows.

## Workflow

```mermaid
flowchart LR
    A[New email] --> B[FastAPI POST /events]
    B --> C[Save event JSON]
    C --> D[LLM extracts listings]
    D --> F[Describe each listing as text]
    F --> G[OpenAI embedding]
    G --> H[(Postgres listings table)]
    I[Question] --> J[Embed the question]
    J --> K[SQL filters and similarity ranking]
    H --> K
    K -->|GET /search| L[Best matching listings]
    K -->|POST /ask| M[LLM answers from those listings]
    M --> N[Answer with cited sources]
```

RAG (Retrieval-Augmented Generation) has two halves, and the app exposes each one:

- **Retrieval, `GET /search`:** Find the stored data most relevant to a question. The question is embedded, SQL filters remove listings that don't fit (price, rooms), and the rest are ranked by similarity. No LLM writes anything here. You get back the matching listings and read them yourself.
- **Generation, `POST /ask`:** Runs the same retrieval, then makes one more LLM call. The retrieved listings are numbered and put in the prompt, and the LLM answers the question using only those listings. It returns its answer plus the numbers of the listings it used, which the app turns back into `sources`.

Retrieval decides what the LLM can see, so the answer can only be as good as what was retrieved. Generation turns those results into a direct answer, and grounding it in retrieved data keeps it from inventing listings.

## The RAG Pipeline, Step by Step

Where each step happens in the [practice scripts](week4/pgvector-setup/README.md) and in the app:

| Step | Practice scripts | App |
|------|------------------|-----|
| Document processing: load and chunk | `listings.py` loads the CSV and turns each listing into one line of text. No chunking: a listing is about 30 tokens, so it is already one chunk. | `apartment_workflow.py` extracts listings from an email, `listing_to_text` turns each into one line |
| Embedding generation | `get_embeddings` in `listings.py`, used by scripts 1, 2, and 3 | `create_embedding` in `database/embedding.py` |
| Vector storage | Script 1 (`1-basic-operations.py`, plain SQL) and script 2 (`2-sqlalchemy-example.py`, SQLAlchemy) | `save_listings` in `database/repository.py` |
| Similarity search | `search` in scripts 1 and 2, `retrieve` in script 3 (`3-rag-example.py`) | `search_listings`, behind `GET /search` |
| Response generation | Script 3 only | `ask_workflow.py`, behind `POST /ask` |

Chunking matters for long text such as articles or PDFs, which are split into pieces so each vector covers one topic. Short records like listings are embedded whole.

## Run Once: Set Up and Create the Table

1. **Fill in `.env`** from `.env.example`: `OPENAI_API_KEY` and `DATABASE_URL`.
2. **Install packages:** `uv sync`
3. **Start the database:** `docker compose up -d`. If port 5432 is taken by another project, set `POSTGRES_PORT=5434` in `.env` and use `localhost:5434` in `DATABASE_URL`.
4. **Practice (recommended):** follow the [pgvector practice](week4/pgvector-setup/README.md) to see the raw SQL behind the app.
5. **Create the table:** `uv run app/database/create_tables.py`
6. **Load the emails you already captured:** `uv run app/database/load_events.py`. Run it again if emails arrived while the app was stopped.

## Run Every Time: Start the App and Ask Questions

1. **Start the database:** `docker compose up -d`
2. **Start the app** and keep the terminal open: `cd app` then `uv run main.py`
3. **To receive new emails,** start the tunnel and update the webhook as in [Start a New Session](docs/start-new-session.md).
4. **Search or ask** at `http://localhost:8000/docs`, or:

   ```bash
   curl "http://localhost:8000/search?q=garden+flat+with+terrace&max_price=1500&min_rooms=2"

   curl -X POST http://localhost:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "Which flats would suit a couple on a small budget?"}'
   ```

   Or ask from the terminal without the app: `uv run app/workflows/ask_workflow.py "Is there a flat with a garden?"`

To stop, press Ctrl+C on `main.py`, then run `docker compose down`. Your data is kept.

## Code Map

| File | What it does |
|------|--------------|
| `docker-compose.yml` | Runs Postgres 17 with pgvector |
| `app/schemas/listing_schema.py` | Listing and API models, and `listing_to_text` |
| `app/database/models.py` | The `listings` table |
| `app/database/create_tables.py` | Enables pgvector and creates the table |
| `app/database/repository.py` | `save_listings` and `search_listings` |
| `app/database/embedding.py` | `create_embedding` |
| `app/database/load_events.py` | Loads listings from saved events |
| `app/workflows/apartment_workflow.py` | Extracts listings from an email and saves them |
| `app/workflows/ask_workflow.py` | RAG: retrieve, then generate an answer with sources |
