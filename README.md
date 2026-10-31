# Week 6: Deployment, CI/CD, and Cloud Operations

Goal: get the assistant running live on the internet, with a database that isn't on my laptop, and a fixed webhook address so new emails are processed without a tunnel or a terminal left open.

## Live Deployment

| | |
|---|---|
| App | [https://assistant-26484711792.europe-west3.run.app](https://assistant-26484711792.europe-west3.run.app) (asks for `APP_PASSWORD`, any username) |
| Nylas webhook | `https://assistant-26484711792.europe-west3.run.app/events` |
| Cloud Run | Service `assistant` in project `ai-personal-assistant-lp`, region `europe-west3` (Frankfurt) |
| Database | Supabase, Central EU (Frankfurt), table `listings` |

## This Week's Goals

By the end of this week, we can:

- distinguish local, virtual machine, container, platform, and serverless deployment approaches;
- explain how continuous integration and continuous deployment (CI/CD) automate testing and releases;
- package the app with Docker and test the image locally;
- deploy the FastAPI app on Google Cloud Run;
- use Supabase for hosted Postgres with pgvector;
- keep the deployed app private with a password, while Nylas can still reach `/events`; and
- understand Streamlit as a simpler alternative for an interactive demo.

## Deployment Types and the Approach Used Here

| Type | What you manage | Typical use |
|------|-----------------|-------------|
| Local process | Application and machine | Development and debugging |
| Virtual machine | OS, runtime, application, and scaling | Maximum infrastructure control |
| Container | Image and application configuration | Portable, repeatable deployments |
| Platform as a service | Application and configuration | Simple web application hosting |
| Serverless container | Container and configuration | APIs and jobs that scale on demand |

This project uses a **serverless container deployment**. Docker supplies one repeatable image of the app, and Cloud Run manages the servers, HTTPS, startup, and scaling. Supabase runs the database. There is no VM, reverse proxy, or domain to manage.

## CI/CD Concepts

CI/CD is the automated path from a code change to a tested deployment:

1. A developer pushes a change to the repository.
2. **Continuous integration (CI)** installs dependencies and runs automated checks such as tests, linting, and a Docker build.
3. A successful build produces an immutable container image.
4. **Continuous delivery/deployment (CD)** promotes that image to the target environment, runs smoke tests, and makes rollback possible.

The steps below do these stages by hand so each part is visible. `gcloud run deploy --source .` already uses Cloud Build to build the image. A GitHub Actions workflow could later run the tests and the same deploy command on every approved change, without changing the app.

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

## Deploy, Step by Step

### 1. Test the Docker image locally

Build the image and run it against the local Docker database before touching any cloud service:

```bash
docker compose up -d
docker build -t assistant .
docker run --rm -p 8080:8080 --network ai-personal-assistant_default \
  --env-file .env \
  -e PORT=8080 \
  -e APP_PASSWORD=test \
  -e DATABASE_URL="postgresql://postgres:postgres@db:5432/postgres" \
  assistant
```

Inside the Docker network the database is reachable as `db` on port 5432, not `localhost`. In a second terminal:

```bash
curl -i http://localhost:8080/docs                          # 401: password required
curl -u any:test "http://localhost:8080/search?q=garden"    # listings from your local database
```

Press Ctrl+C to stop the container.

### 2. Set up a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com), open the project dropdown, click **New Project**, name it, and click **Create**.
2. Under **Billing**, link a billing account to the project.
3. Install the `gcloud` CLI, then log in and enable the APIs this deployment needs:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

Enabling them upfront avoids interactive prompts in the middle of `gcloud run deploy`.

### 3. Create the Supabase database

1. Sign up at [supabase.com](https://supabase.com) and click **New Project**. Pick **Central EU (Frankfurt)**, close to your Nylas EU region and Cloud Run. Save the database password.
2. Wait a minute or two for it to be ready.
3. Click **Connect** and copy the **Session pooler** connection string. Cloud Run can't reach the direct connection, which needs IPv6.
4. Replace `[YOUR-PASSWORD]` in it with your database password. This is your `DATABASE_URL`.

### 4. Check the connection and create the table

Run the table script on your laptop against Supabase. It enables pgvector and creates `listings`, so it also proves the connection string works:

```bash
DATABASE_URL="your Supabase URL" uv run app/database/create_tables.py
```

The `Dockerfile` runs the same script on every start, so this step is only a check. The script skips tables that already exist.

### 5. Write the Cloud Run settings

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

`WEBHOOK_SECRET` stays empty until step 7. The file is in `.gitignore`, so it is never committed.

### 6. Deploy the app to Cloud Run

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

Cloud Build builds the `Dockerfile`, and Cloud Run prints the service URL, such as `https://assistant-xxxx.europe-west3.run.app`. Open it, enter any username and your `APP_PASSWORD`, and you see the main page.

What the flags do:

- **`--allow-unauthenticated`:** lets Nylas reach the app. The password check in `main.py` protects every page except `/events`, and `/events` checks the Nylas signature.
- **`--no-cpu-throttling`:** the app replies to Nylas first, then classifies the email in the background. Cloud Run normally slows the CPU right after the reply, so this keeps it running until the work is done.
- **`--max-instances 1`:** the main page keeps results in memory, so every request has to reach the same instance.

### 7. Create the webhook

On your laptop, set `SERVER_URL` in your local `.env` to the Cloud Run URL, then run `cd app/config` and `uv run config_webhook.py`.

Put the printed secret into `WEBHOOK_SECRET` in `cloudrun.env.yaml`, then load it without rebuilding:

```bash
gcloud run services update assistant --region europe-west3 --env-vars-file cloudrun.env.yaml
```

Delete the old trycloudflare webhook in the Nylas Dashboard, so Nylas stops reporting it as failing.

### 8. Test the live deployment end to end

Send yourself an apartment listing email, then check:

- The logs show `POST /events 200`: `gcloud run services logs read assistant --region europe-west3`
- The email shows up on the main page with its listings.
- In Supabase, **Table Editor** shows the new rows in `listings`.

Then try retrieval and generation on the live URL:

```bash
curl -u any:YOUR_APP_PASSWORD "https://YOUR-SERVICE-URL/search?q=garden+flat"

curl -u any:YOUR_APP_PASSWORD -X POST https://YOUR-SERVICE-URL/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which flats would suit a couple on a small budget?"}'
```

Quote the `/search` URL: `?` and `&` have special meaning to the shell.

### Optional: load emails you captured locally

Run the loader on your laptop against Supabase:

```bash
DATABASE_URL="your Supabase URL" uv run app/database/load_events.py
```

## Things to Know About the Live App

- **Scale to zero:** after some idle minutes Cloud Run stops the app. The first request afterwards takes a few seconds, and the main page starts empty. Listings stay in Supabase, so `/search` and `/ask` still find them.
- **Saved emails:** the raw event files are written inside the container and disappear when it stops. The extracted listings are what is kept.
- **Re-processing is safe:** `save_listings` skips listings already stored, and `load_events.py` skips emails already in the database, so running the loader again or receiving the same email twice adds no duplicates.

## Why a Service and No Scheduled Job

The app is event driven. Nylas calls `/events` the moment an email arrives, and the app processes it in the background. So the app runs as one always-reachable Cloud Run Service, and there is no batch pipeline to schedule with a Cloud Run Job or Cloud Scheduler. If you later add periodic work, such as a daily summary email, that would be the place for a Job triggered by Cloud Scheduler.

## Security Considerations

- **Password on every page except `/events`:** `/search` and `/ask` make billed OpenAI calls, so they are behind `APP_PASSWORD`. `/events` is open to the internet, but rejects any request without a valid Nylas signature.
- **SQL injection is not a risk here:** every query in `app/database/repository.py` goes through SQLAlchemy, which passes values as parameters. User input is never pasted into a raw SQL string.
- **Secrets as environment variables:** `cloudrun.env.yaml` puts the keys into Cloud Run as plain environment variables, visible to anyone with access to the Cloud Run service in the console. For a team project, [Google Secret Manager](https://cloud.google.com/run/docs/configuring/services/secrets) is the stronger option, used with `--set-secrets` instead of `--env-vars-file`.
- **Cost abuse is reduced, not solved:** the password stops strangers, but there is no rate limit or billing alert yet. Setting a budget alert in Google Cloud and a usage limit in OpenAI is a good next step.

## Alternative: a Simple Interactive Streamlit Demo

Streamlit is useful when the goal is a quick human-facing demo rather than a reusable API. A small Streamlit page could call the deployed `/search` and `/ask` endpoints and show the listings and answers, deployed separately on Streamlit Community Cloud.

This is an extra presentation layer, not a replacement:

- FastAPI receives the Nylas webhook and provides JSON endpoints.
- Streamlit provides an interactive interface with very little UI code.
- Postgres stays the source of truth.

## Day-to-Day

| Task | Command |
|------|---------|
| Deploy new code | The `gcloud run deploy` command from step 6 |
| Change a setting | Edit `cloudrun.env.yaml`, then the `gcloud run services update` command from step 7 |
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
