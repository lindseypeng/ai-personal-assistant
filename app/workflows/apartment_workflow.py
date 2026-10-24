import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from nylas import Client
from openai import OpenAI
from pydantic import BaseModel, Field

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing schemas and database

from database.repository import save_listings
from schemas.listing_schema import Listing
from schemas.nylas_email_schema import EmailObject
from schemas.nylas_webhook_schema import WebhookEvent

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EVENTS_DIR = BASE_DIR / "requests" / "events"
LABEL_NAME = "Apartments"
READ_ONLY_LABELS = {"SENT", "DRAFT", "CHAT"}
MAX_TEXT_CHARS = 40000  # limit on the email text sent to the LLM

PROMPT = """
Decide whether the email contains apartment listings: rental or sale offers for specific
apartments or houses, including listing alerts and digests from property sites.
If it does, extract every listing in the email, one entry per property.
Use null for any detail the email does not state. Do not guess.
"""


class ApartmentCheck(BaseModel):
    is_listing: bool
    confidence: float = Field(ge=0, le=1, description="How sure you are of the is_listing answer, whether it is true or false")
    listings: list[Listing] = Field(description="Every listing in the email, empty if none")


# --------------------------------------------------------------
# Step 1: Load a saved event
# --------------------------------------------------------------


def load_email(event_id: str) -> EmailObject:
    with open(EVENTS_DIR / f"{event_id}.json") as f:
        event = WebhookEvent(**json.load(f))
    return EmailObject(**event.data["object"])


# --------------------------------------------------------------
# Step 2: Classify and extract details with an LLM
# --------------------------------------------------------------


def html_to_text(html: str) -> str:
    """Strip HTML down to text, keeping each link's URL next to its text."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r'(?is)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def check_apartment(email: EmailObject) -> ApartmentCheck:
    text = html_to_text(email.body)[:MAX_TEXT_CHARS]
    response = OpenAI().responses.parse(
        model="gpt-4o-mini",
        instructions=PROMPT,
        input=f"From: {email.from_[0].email}\nSubject: {email.subject}\n\n{text}",
        text_format=ApartmentCheck,
    )
    return response.output_parsed


# --------------------------------------------------------------
# Step 3: Save listings to Postgres with their embeddings
# --------------------------------------------------------------


def save_listing(email: EmailObject, result: ApartmentCheck) -> int:
    return save_listings(email, result.listings)


# --------------------------------------------------------------
# Step 4: Label the email in Gmail after confirmation
# --------------------------------------------------------------


def label_email(email: EmailObject) -> None:
    nylas = Client(
        api_key=os.environ.get("NYLAS_API_KEY", ""),
        api_uri=os.environ.get("NYLAS_API_URI", ""),
    )
    folders = nylas.folders.list(email.grant_id).data
    label = next((f for f in folders if f.name == LABEL_NAME), None)
    if label is None:
        label = nylas.folders.create(email.grant_id, request_body={"name": LABEL_NAME}).data

    current = nylas.messages.find(email.grant_id, email.id).data.folders
    if label.id not in current:
        # Gmail rejects system labels such as SENT, so send back only the ones it allows
        allowed = [f for f in current if f not in READ_ONLY_LABELS]
        nylas.messages.update(
            email.grant_id, email.id, request_body={"folders": allowed + [label.id]}
        )


def run(event_id: str) -> None:
    email = load_email(event_id)
    result = check_apartment(email)
    print(f"Subject: {email.subject}")
    print(f"Apartment listing: {result.is_listing} (confidence {result.confidence:.2f})")

    if not result.is_listing:
        return

    print(f"{len(result.listings)} listing(s) found:")
    for listing in result.listings:
        print(listing.model_dump_json(indent=2))
    saved = save_listing(email, result)
    print(f"Saved {saved} new listing(s) to Postgres")

    if input(f"Add the '{LABEL_NAME}' label in Gmail? [y/N] ").strip().lower() == "y":
        label_email(email)
        print("Labeled.")


if __name__ == "__main__":
    run(sys.argv[1])  # event id: a file name in requests/events/ without .json
