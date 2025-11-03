import argparse
import logging
from pathlib import Path
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session

from backend.app.database import engine
from backend.app.models import SQLModel

from backend.scripts.db_utils.loaders_optimized import DataLoader

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def disable_fk_constraints() -> None:
    """Disable foreign key constraints during import"""
    with Session(engine) as session:
        session.exec(text("SET session_replication_role = 'replica';"))
        session.commit()
        logger.info("[dbcli] Foreign key constraints disabled")


def enable_fk_constraints() -> None:
    """Re-enable foreign key constraints after import"""
    with Session(engine) as session:
        session.exec(text("SET session_replication_role = 'origin';"))
        session.commit()
        logger.info("[dbcli] Foreign key constraints enabled")


def clear_database() -> None:
    """Clear all tables (Drop and recreate)"""
    logger.info("=" * 70)
    logger.info("DATABASE CLEAR OPERATION")
    logger.info("=" * 70 + "\n")
    logger.info("[dbcli] Dropping and recreating all tables...")

    try:
        disable_fk_constraints()
        SQLModel.metadata.drop_all(engine)
        logger.info("  ✓ Dropped all tables")

        SQLModel.metadata.create_all(engine)
        logger.info("  ✓ Created all tables")
        enable_fk_constraints()

        logger.info("\n✓ Database cleared successfully\n")
    except Exception as e:
        logger.error(f"\n✗ Error clearing database: {e}\n")
        raise


def import_all_data(data_dir: Path | None = None) -> None:
    """Import all tables in correct order"""
    if data_dir is None:
        # Go up to repo root: dbcli.py -> db_utils -> scripts -> backend -> repo root
        data_dir = Path(__file__).parent.parent.parent.parent / "data"

    start_time = datetime.now()

    logger.info("=" * 70)
    logger.info("ViteVue Data Warehouse - Import Pipeline")
    logger.info("=" * 70 + "\n")

    disable_fk_constraints()

    loader = DataLoader(data_dir)

    steps = [
        ("Areas", loader.load_areas),
        ("Transaction Lookups", loader.load_transaction_lookups),
        ("Property Types", loader.load_property_types),
        ("Property Sub-Types", loader.load_property_sub_types),
        ("Master Projects", loader.load_master_projects),
        ("Developers", loader.load_developers),
        ("Projects", loader.load_projects),
        ("Land Registry", loader.load_land_registry),
        ("Buildings", loader.load_buildings),
        ("Units", loader.load_units),
        ("Transactions", loader.load_transactions),
        ("Rent Contracts", loader.load_rent_contracts),
    ]

    errors = []
    for step_name, step_func in steps:
        try:
            step_func()
        except Exception as e:
            error_msg = f"{step_name}: {str(e)}"
            errors.append(error_msg)
            logger.error(f"\n✗ Error in {step_name}: {e}\n")
            continue

    enable_fk_constraints()

    elapsed = datetime.now() - start_time

    logger.info("=" * 70)
    if errors:
        logger.info("[dbcli] IMPORT COMPLETED WITH ERRORS")
        logger.info("=" * 70)
        logger.info("\nFailed steps:")
        for error in errors:
            logger.info(f"  - {error}")
        logger.info("\nRun again to resume from where it failed.")
    else:
        logger.info("✓ IMPORT COMPLETE!")
        logger.info("=" * 70)

    logger.info(f"\nTotal time: {elapsed}\n")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="ViteVue Data Import Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all tables (drop and recreate)",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Import all data (skips already loaded tables)",
    )
    parser.add_argument(
        "--data-dir", type=Path, help="Path to data directory (default: ./data)"
    )

    args = parser.parse_args()

    if not args.clear and not args.do_import:
        parser.error("Must specify at least one of --clear or --import")

    if args.clear:
        confirm = input('[WARNING] This will drop and recreate the entire database\n' \
        'Please type "CONFIRM" if you want to proceed: ')
        if confirm == "CONFIRM":
            clear_database()
        else:
            logger.error("\nAborting!")
            exit

    if args.do_import:
        import_all_data(args.data_dir)


if __name__ == "__main__":
    main()
