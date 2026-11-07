"""Measure how often the AI judge is right about "is this email a listing?".

Labels live in requests/labels.json (ignored by Git, since the events are personal email):
    {"<event file name without .json>": true, ...}

Run from the app folder:  python evals/judge_eval.py
Nothing is saved to the database. Every email becomes a Langfuse trace tagged "eval",
with a "correct" score, so you can open the mistakes in Langfuse and see why.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client, observe, propagate_attributes

sys.path.append(str(Path(__file__).resolve().parent.parent))  # allow importing workflows

from workflows.apartment_workflow import EVENTS_DIR, check_apartment, is_listing_email, load_email

load_dotenv()

LABELS_FILE = EVENTS_DIR.parent / "labels.json"


# --------------------------------------------------------------
# Step 1: Run both judge steps on one email, the same way the app does
# --------------------------------------------------------------


@observe(name="eval email", capture_input=False)
def judge(event_id: str, expected: bool) -> dict:
    email = load_email(event_id)
    langfuse = get_client()
    langfuse.update_current_span(
        input={"from": email.from_[0].email, "subject": email.subject, "expected": expected}
    )

    triage = is_listing_email(email)
    predicted = triage and check_apartment(email).is_listing

    langfuse.score_current_trace(name="correct", value=1 if predicted == expected else 0, data_type="BOOLEAN")
    return {"subject": email.subject, "expected": expected, "triage": triage, "predicted": predicted}


# --------------------------------------------------------------
# Step 2: Count right and wrong answers
# --------------------------------------------------------------


def confusion(results: list[dict], key: str) -> dict:
    counts = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    for r in results:
        if r[key]:
            counts["TP" if r["expected"] else "FP"] += 1
        else:
            counts["FN" if r["expected"] else "TN"] += 1
    return counts


def report(name: str, c: dict) -> None:
    total = sum(c.values())
    accuracy = (c["TP"] + c["TN"]) / total
    precision = c["TP"] / (c["TP"] + c["FP"]) if c["TP"] + c["FP"] else float("nan")
    recall = c["TP"] / (c["TP"] + c["FN"]) if c["TP"] + c["FN"] else float("nan")
    print(f"\n{name}")
    print(f"  TP {c['TP']}  FP {c['FP']}  FN {c['FN']}  TN {c['TN']}")
    print(f"  accuracy {accuracy:.0%}  precision {precision:.0%}  recall {recall:.0%}")


def run() -> None:
    labels = json.loads(LABELS_FILE.read_text())
    results = []
    # The "eval" tag keeps these traces apart from real emails in Langfuse
    with propagate_attributes(tags=["eval"]):
        for event_id, expected in labels.items():
            r = judge(event_id, expected)
            mark = "ok   " if r["predicted"] == expected else "WRONG"
            print(f"{mark} expected={expected!s:5} triage={r['triage']!s:5} final={r['predicted']!s:5} {r['subject'][:60]}")
            results.append(r)

    # Triage alone: wrongly passing a non-listing on is cheap (extraction catches it),
    # wrongly stopping a listing is not (it is lost for good)
    report("Step 1, triage (sender and subject)", confusion(results, "triage"))
    report("Final decision (triage, then extraction)", confusion(results, "predicted"))
    get_client().flush()


if __name__ == "__main__":
    run()
