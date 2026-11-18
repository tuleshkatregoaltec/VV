"""Send one test email through Brevo and record it in the Connectors › Email store.

Nothing is written to the database; the organization is only looked up (read only) so the send
shows on that organization's Tracking tab. Run from VV/backend with the env loaded:

    set -a; . ../.env; set +a
    uv run python -m scripts.crm.send_test_email --to someone@example.com
"""

import argparse
import asyncio

from sqlalchemy import text

from app.config import settings
from app.crm import email_pipeline, email_store
from app.postgres.client import close_postgres, get_postgres_engine


async def organization_id(given: str | None) -> str:
    if given or settings.BREVO_INBOUND_ORGANIZATION_ID:
        return given or settings.BREVO_INBOUND_ORGANIZATION_ID
    async with get_postgres_engine().connect() as conn:
        rows = (await conn.execute(text("SELECT id, name FROM organizations ORDER BY name"))).all()
    if len(rows) != 1:
        names = ", ".join(f"{r.name} ({r.id})" for r in rows)
        raise SystemExit(f"Pick an organization with --org: {names}")
    return str(rows[0].id)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--org", default=None, help="organization id (default: the only one)")
    parser.add_argument("--subject", default="Vitevue CRM · test email for {{first_name}}")
    parser.add_argument(
        "--body",
        default=(
            "Hi {{first_name}},\n\nThis is a test email from Vitevue CRM (Connectors › Email),"
            " sent through Brevo.\n\nIf you can read this, outbound email works.\n\nVitevue"
        ),
    )
    args = parser.parse_args()
    try:
        org = await organization_id(args.org)
    finally:
        await close_postgres()
    send = await email_pipeline.send_to_address(
        organization_id=org,
        user_id="script:send_test_email",
        to_email=args.to,
        to_name=args.name,
        subject=args.subject,
        body=args.body,
    )
    print(f"send #{send.id} to {send.to_email}: {send.status}")
    if send.error:
        print(f"Brevo said: {send.error}")
    else:
        print(f"Brevo message id: {send.message_id}")
    print(f"Recorded in {email_store.store_path()}")


if __name__ == "__main__":
    asyncio.run(main())
