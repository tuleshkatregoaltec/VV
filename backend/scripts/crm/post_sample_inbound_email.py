"""Post a sample Brevo inbound-parsing email to a running backend, for testing without DNS.

Brevo cannot reach localhost, so this stands in for it. Run from VV/backend with the env loaded:

    set -a; . ../.env; set +a
    uv run python -m scripts.crm.post_sample_inbound_email --from someone@example.com
    uv run python -m scripts.crm.post_sample_inbound_email --from sara@example.com --reply-to-send 12

Without --reply-to-send the email is matched by sender, or becomes a new lead in
BREVO_INBOUND_ORGANIZATION_ID. With it, it is addressed to reply+<send id>@BREVO_INBOUND_DOMAIN.
"""

import argparse
import os
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="sender", required=True, help="sender email address")
    parser.add_argument("--name", default="Test Sender", help="sender display name")
    parser.add_argument("--subject", default="Interested in a 2 bed in Dubai Marina")
    parser.add_argument(
        "--body", default="Hi, I am looking to buy a 2 bedroom in Dubai Marina, budget 2.5m."
    )
    parser.add_argument("--reply-to-send", type=int, help="the send id this replies to")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()

    secret = os.environ.get("BREVO_WEBHOOK_SECRET")
    if not secret:
        raise SystemExit("BREVO_WEBHOOK_SECRET is not set; load the env first.")
    domain = os.environ.get("BREVO_INBOUND_DOMAIN") or "reply.example.com"
    to = f"reply+{args.reply_to_send}@{domain}" if args.reply_to_send else f"hello@{domain}"

    item = {
        "MessageId": f"<{uuid.uuid4()}@sample.local>",
        "From": {"Name": args.name, "Address": args.sender},
        "To": [{"Name": None, "Address": to}],
        "Subject": args.subject,
        "RawTextBody": args.body,
        "ExtractedMarkdownMessage": args.body,
        "Attachments": [],
        "SentAtDate": format_datetime(datetime.now(timezone.utc)),
    }
    res = httpx.post(
        f"{args.api}/api/v1/crm/email/brevo-inbound",
        params={"secret": secret},
        json={"items": [item]},
        timeout=20,
    )
    print(res.status_code, res.text)


if __name__ == "__main__":
    main()
