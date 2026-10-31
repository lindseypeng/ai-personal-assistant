# Week 5: Deploy the Assistant

Run the assistant live on the internet, so new emails are processed without a tunnel or a laptop left on.

## Goals

1. Package the app with Docker and test the image locally.
2. Move the database to Supabase (hosted Postgres with pgvector).
3. Deploy the app to Google Cloud Run, with a fixed HTTPS URL for the Nylas webhook.
4. Keep it private: every page asks for a password, except `/events`, which checks the Nylas signature.

## Live Deployment

| | |
|---|---|
| App | [assistant-26484711792.europe-west3.run.app](https://assistant-26484711792.europe-west3.run.app) (any username, password is `APP_PASSWORD`) |
| Cloud Run | Service `assistant`, project `ai-personal-assistant-lp`, region `europe-west3` |
| Database | Supabase, Central EU (Frankfurt), table `listings` |

```mermaid
flowchart LR
    N[Nylas] -->|/events| R[Cloud Run: FastAPI]
    U[You, with password] --> R
    R --> S[(Supabase)]
```

## How Emails Are Processed

1. **Sender and subject check.** Senders in `LISTING_DOMAINS` (`immobilienscout24.de`) count as listings. Other emails get one small LLM call with only the sender and subject. Everything else stops here.
2. **Extraction.** Only for listing emails: the raw event is saved, the full body goes to the LLM, and the listings are saved to the database.

## Deploy, Step by Step

### 1. Test the Docker image locally

```bash
docker compose up -d
docker build -t assistant .
docker run --rm -p 8080:8080 --network ai-personal-assistant_default --env-file .env \
  -e PORT=8080 -e APP_PASSWORD=test \
  -e DATABASE_URL="postgresql://postgres:postgres@db:5432/postgres" \
  assistant
```

Open `http://localhost:8080`, log in with any username and `test`, then stop it with Ctrl+C.

### 2. Create a Google Cloud project

Create a project in the [Cloud Console](https://console.cloud.google.com) and link a billing account (a small budget alert is a good idea). Then:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

### 3. Create the Supabase database

Create a project at [supabase.com](https://supabase.com) in **Central EU (Frankfurt)**. Click **Connect**, copy the **Session pooler** string, and put in your database password. This is your `DATABASE_URL`. The app creates the `listings` table itself on start.

### 4. Store the secrets and settings

Keys and passwords go into Secret Manager, so the Cloud Console shows only a reference, never the value. For each one, run this with your own value:

```bash
printf '%s' 'YOUR_VALUE' | gcloud secrets create openai-api-key --data-file=-
```

| Secret | Value |
|---|---|
| `openai-api-key` | OpenAI API key |
| `nylas-api-key` | Nylas API key |
| `database-url` | Supabase session pooler string |
| `app-password` | Password for the app |
| `webhook-secret` | `placeholder` for now, replaced in step 6 |

Create a service account for the app that can only read these secrets:

```bash
gcloud iam service-accounts create assistant-run
for s in openai-api-key nylas-api-key database-url app-password webhook-secret; do
  gcloud secrets add-iam-policy-binding $s --role=roles/secretmanager.secretAccessor \
    --member=serviceAccount:assistant-run@YOUR_PROJECT_ID.iam.gserviceaccount.com
done
```

The settings that are not secret go in `cloudrun.env.yaml` in the repo root (Git ignores it):

```yaml
NYLAS_API_URI: "https://api.eu.nylas.com"
NYLAS_CLIENT_ID: "..."
NYLAS_GRANT_ID: "..."
```

### 5. Deploy

```bash
gcloud run deploy assistant --source . --region europe-west3 \
  --allow-unauthenticated --no-cpu-throttling --max-instances 1 \
  --env-vars-file cloudrun.env.yaml \
  --service-account assistant-run@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --set-secrets=OPENAI_API_KEY=openai-api-key:latest,NYLAS_API_KEY=nylas-api-key:latest,DATABASE_URL=database-url:latest,APP_PASSWORD=app-password:latest,WEBHOOK_SECRET=webhook-secret:latest
```

It prints the service URL. The flags:

- `--allow-unauthenticated`: lets Nylas reach `/events`. The app's password protects everything else.
- `--no-cpu-throttling`: lets the email finish processing after the app replies to Nylas.
- `--max-instances 1`: keeps costs predictable for a personal app.
- `--set-secrets`: loads each secret into the app as an environment variable.
- `--service-account`: runs the app as `assistant-run` instead of the default account, which can edit the whole project.

### 6. Create the webhook

Set `SERVER_URL` in your local `.env` to the service URL, then:

```bash
cd app/config && uv run config_webhook.py
```

Save the printed secret as a new version and restart the app so it loads it:

```bash
printf '%s' 'PRINTED_SECRET' | gcloud secrets versions add webhook-secret --data-file=-
gcloud run services update assistant --region europe-west3 --update-secrets=WEBHOOK_SECRET=webhook-secret:latest
```

Delete any old tunnel webhook in the Nylas Dashboard.

### 7. Test

Send yourself an apartment listing email. Within about 20 seconds it appears on the main page, and its listings appear in Supabase under **Table Editor**, `listings`.

## Good to Know

- After about 15 idle minutes Cloud Run stops the app, so the next request takes a few seconds. The main page reads saved listings from Supabase, so nothing is lost.
- To redeploy code, run step 5 again. To change a secret, add a new version as in step 6 and run the `services update` command.
- To see the app password: `gcloud secrets versions access latest --secret=app-password`
- Logs: `gcloud run services logs read assistant --region europe-west3`
- Locally nothing changes: leave `APP_PASSWORD` empty and run the app as in [Week 4](https://github.com/lindseypeng/ai-personal-assistant/tree/week-4).
