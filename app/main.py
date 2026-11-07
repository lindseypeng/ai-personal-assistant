# Import packages
import base64
import hashlib
import hmac
import os
from typing import Optional
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from langfuse import get_client, observe
from database.repository import recent_listings, search_listings
from schemas.listing_schema import AskRequest, AskResponse, ListingSearchResult
from schemas.nylas_email_schema import EmailObject
from schemas.nylas_webhook_schema import WebhookEvent
from workflows.apartment_workflow import (
    check_apartment,
    is_listing_email,
    label_email,
    save_listing,
)
from workflows.ask_workflow import ask

load_dotenv(override=True)

# Ids of emails labeled in Gmail since the app started
labeled = set()

# Create the FastAPI app
app = FastAPI()

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")


# Ask for APP_PASSWORD on every page except /events, which Nylas must reach
@app.middleware("http")
async def require_password(request: Request, call_next):
    password = os.environ.get("APP_PASSWORD", "")
    if password and request.url.path != "/events":
        if not check_password(request.headers.get("authorization"), password):
            return PlainTextResponse(
                "Login required", status_code=401, headers={"WWW-Authenticate": "Basic"}
            )
    return await call_next(request)


# Read and insert webhook data
@app.api_route("/events", methods=["GET", "POST"])
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    event: Optional[WebhookEvent] = None,
    x_nylas_signature: Optional[str] = Header(None),
):
    if request.method == "GET":
        challenge = request.query_params.get("challenge")
        if challenge:
            print(" * Nylas connected to the webhook!")
            return PlainTextResponse(challenge)
        return PlainTextResponse(
            "No challenge", status_code=status.HTTP_400_BAD_REQUEST
        )
    # POST method
    body = await request.body()
    is_genuine = verify_signature(
        message=body,
        key=os.environ.get("WEBHOOK_SECRET", "").encode("utf8"),
        signature=x_nylas_signature,
    )
    if not is_genuine:
        return PlainTextResponse("Signature verification failed!", status_code=401)

    if not event:
        return PlainTextResponse("No event data", status_code=400)

    # Classify after replying, so Nylas gets its 200 right away
    background_tasks.add_task(check_listing, event)
    return PlainTextResponse("Webhook received", status_code=200)


# Main page: saved listings from the database, grouped by the email they came from
@app.get("/")
def index(request: Request):
    emails = {}
    for listing in recent_listings():
        email = emails.setdefault(
            listing.email_id,
            {
                "id": listing.email_id,
                "date": datetime.fromtimestamp(listing.email_date).strftime("%Y-%m-%d %H:%M"),
                "subject": listing.subject,
                "listings": [],
            },
        )
        email["listings"].append(listing)
    return templates.TemplateResponse(
        request, "index.html", {"emails": list(emails.values()), "labeled": labeled}
    )


# Label an email with saved listings in Gmail after you confirm it on the main page
@app.post("/label/{email_id}")
def label(email_id: str):
    if any(listing.email_id == email_id for listing in recent_listings()):
        label_email(os.environ.get("NYLAS_GRANT_ID", ""), email_id)
        labeled.add(email_id)
    return RedirectResponse(url="/", status_code=303)


# Search saved listings by meaning, with optional price and room filters
@app.get("/search", response_model=list[ListingSearchResult])
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=50),
    max_price: Optional[float] = None,
    min_rooms: Optional[float] = None,
):
    return search_listings(q, limit=limit, max_price=max_price, min_rooms=min_rooms)


# Answer a question about saved listings: retrieve the closest ones, then let the LLM answer from them
@app.post("/ask", response_model=AskResponse)
def ask_listings(request: AskRequest):
    return ask(request.question, request.limit, request.max_price, request.min_rooms)


# Check sender and subject first. Only listing emails are stored and sent in full to the LLM.
# One Langfuse trace per email: its output is the decision, the steps inside are child spans.
@observe(name="email", capture_input=False)
def check_listing(event: WebhookEvent):
    email_obj = EmailObject(**event.data["object"])
    langfuse = get_client()
    langfuse.update_current_span(
        input={"from": email_obj.from_[0].email, "subject": email_obj.subject},
        metadata={"email_id": email_obj.id},
    )
    if not is_listing_email(email_obj):
        return {"triage": False}
    store_event_json(event)
    result = check_apartment(email_obj)
    saved = save_listing(email_obj, result) if result.is_listing else 0
    # Scores make the judge's answers filterable and chartable in Langfuse
    langfuse.score_current_trace(name="is_listing", value=1 if result.is_listing else 0, data_type="BOOLEAN")
    return {
        "triage": True,
        "is_listing": result.is_listing,
        "confidence": result.confidence,
        "listings_found": len(result.listings),
        "listings_saved": saved,
    }


# Signature verification
def verify_signature(message, key, signature):
    digest = hmac.new(key, msg=message, digestmod=hashlib.sha256).hexdigest()

    return hmac.compare_digest(digest, signature)


# The browser login sends "Basic base64(username:password)", any username is accepted
def check_password(authorization, password):
    scheme, _, encoded = (authorization or "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        _, _, given = base64.b64decode(encoded).decode("utf8").partition(":")
    except ValueError:
        return False
    return hmac.compare_digest(given, password)


def store_event_json(event: WebhookEvent):
    base_dir = Path(__file__).resolve().parent.parent
    events_dir = base_dir / "requests" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    filename = events_dir / f"{uuid.uuid1()}.json"
    with open(filename, "w") as f:
        f.write(event.model_dump_json())


# Run our application
if __name__ == "__main__":
    import uvicorn

    # Cloud Run sets PORT, locally it is 8000
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
