import sys
from pathlib import Path

from sqlalchemy import select

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing workflows

from database.connection import SessionLocal
from database.models import ListingModel
from workflows.apartment_workflow import EVENTS_DIR, check_apartment, load_email, save_listing


def load_events() -> None:
    """Run the apartment workflow on every saved event and store the listings in Postgres."""
    with SessionLocal() as db:
        stored = set(db.scalars(select(ListingModel.email_id).distinct()))

    for path in sorted(EVENTS_DIR.glob("*.json")):
        email = load_email(path.stem)
        if email.id in stored:
            print(f"Skip (already stored): {email.subject}")
            continue
        result = check_apartment(email)
        if result.is_listing:
            stored.add(email.id)
            print(f"Saved {save_listing(email, result)} listing(s): {email.subject}")
        else:
            print(f"No listings: {email.subject}")


if __name__ == "__main__":
    load_events()
