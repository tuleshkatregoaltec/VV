"""Build a tenant's stored ownership assessment ahead of its first Owners page load.

    uv run python -m scripts.crm.rebuild_owner_assessment <organization_id> [...]

The Owners reads build it on demand when it is missing or its inputs changed; running this
after an import or a deploy keeps that wait away from the agent's first click.
"""

import asyncio
import logging.config
import sys

from app.core.logging_config import LOGGING_CONFIG
from app.crm import owner_store
from app.postgres.client import close_postgres, get_postgres_engine


async def main(organization_ids: list[str]) -> int:
    logging.config.dictConfig(LOGGING_CONFIG)
    engine = get_postgres_engine()
    status = 0
    try:
        for organization_id in organization_ids:
            state = await owner_store._build_exclusively(engine, organization_id)
            if state is None:
                print(f"{organization_id}: another process is already building it")
                continue
            print(
                f"{organization_id}: generation {state.generation}, "
                f"{state.warehouse_status}, checked {state.checked_at.isoformat()}"
            )
    except Exception as error:  # noqa: BLE001 - report and exit non-zero
        print(f"failed: {type(error).__name__}: {error}", file=sys.stderr)
        status = 1
    finally:
        await close_postgres()
    return status


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
