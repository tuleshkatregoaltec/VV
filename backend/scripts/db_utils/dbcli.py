import argparse
import logging
from pathlib import Path
from datetime import datetime

from sqlalchemy import text
from sqlmodel import Session

from backend.app.db.session import engine
from backend.app.db.models import (
    Area,
    TransactionGroup,
    TransactionProcedure,
    PropertyType,
    PropertySubType,
    MasterProject,
    Developer,
    Project,
    LandRegistry,
    Building,
    Unit,
    Transaction,
    RentContract,
)

from backend.scripts.db_utils.loaders_optimized import DataLoader
from backend.scripts.db_utils.schema import migrate_schema, clear_database as clear_db
from backend.scripts.db_utils.verification import verify_import

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def disable_fk_constraints() -> None:
    """Disable foreign key constraints during import."""
    with Session(engine) as session:
        session.exec(text("SET session_replication_role = 'replica';"))
        session.commit()
        logger.info("[dbcli] Foreign key constraints disabled")


def enable_fk_constraints() -> None:
    """Re-enable foreign key constraints after import."""
    with Session(engine) as session:
        session.exec(text("SET session_replication_role = 'origin';"))
        session.commit()
        logger.info("[dbcli] Foreign key constraints enabled")


def migrate_schema_cmd() -> None:
    """Update database schema to match current models without losing data."""
    logger.info("=" * 70)
    logger.info("SCHEMA MIGRATION")
    logger.info("=" * 70 + "\n")

    try:
        changes_made = migrate_schema()

        if changes_made:
            logger.info("\n✓ Schema migration completed successfully\n")
        else:
            logger.info("✓ Schema is already up to date\n")

    except Exception as e:
        logger.error(f"\n✗ Error during schema migration: {e}\n")
        raise


def clear_db() -> None:
    """Clear all tables (Drop and recreate)."""
    logger.info("=" * 70)
    logger.info("DATABASE CLEAR OPERATION")
    logger.info("=" * 70 + "\n")
    logger.info("[dbcli] Dropping and recreating all tables...")

    try:
        clear_db(disable_fk_constraints, enable_fk_constraints)
        logger.info("\n✓ Database cleared successfully\n")
    except Exception as e:
        logger.error(f"\n✗ Error clearing database: {e}\n")
        raise


def verify_data(data_dir: Path | None = None) -> bool:
    """Verify imported data against CSV sources."""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent.parent / "data"

    models = {
        "Area": Area,
        "TransactionGroup": TransactionGroup,
        "TransactionProcedure": TransactionProcedure,
        "PropertyType": PropertyType,
        "PropertySubType": PropertySubType,
        "MasterProject": MasterProject,
        "Developer": Developer,
        "Project": Project,
        "LandRegistry": LandRegistry,
        "Building": Building,
        "Unit": Unit,
        "Transaction": Transaction,
        "RentContract": RentContract,
    }

    return verify_import(data_dir, models)


def import_all_data(data_dir: Path | None = None) -> None:
    """Import all tables in correct order."""
    if data_dir is None:
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


def reload_master_projects(data_dir: Path | None = None) -> None:
    """Reload master projects table with fixed logic."""
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent.parent / "data"

    logger.info("=" * 70)
    logger.info("Reloading Master Projects")
    logger.info("=" * 70 + "\n")

    disable_fk_constraints()

    try:
        with Session(engine) as session:
            result = session.exec(text("DELETE FROM master_projects"))
            deleted = result.rowcount
            session.commit()
            logger.info(f"✓ Deleted {deleted} existing master projects\n")

        loader = DataLoader(data_dir)
        loader.load_master_projects()

        logger.info("\n✓ Master projects reloaded successfully\n")

    except Exception as e:
        logger.error(f"\n✗ Error reloading master projects: {e}\n")
        raise
    finally:
        enable_fk_constraints()


def main():
    """Main CLI entry point."""
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
        "--migrate-schema",
        action="store_true",
        help="Update database schema to match models.py without losing data",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Import all data (skips already loaded tables)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify imported data against CSV sources",
    )
    parser.add_argument(
        "--reload-master-projects",
        action="store_true",
        help="Reload master projects table with fixed logic",
    )
    parser.add_argument(
        "--data-dir", type=Path, help="Path to data directory (default: ./data)"
    )

    args = parser.parse_args()

    if not any(
        [
            args.clear,
            args.migrate_schema,
            args.do_import,
            args.verify,
            args.reload_master_projects,
        ]
    ):
        parser.error(
            "Must specify at least one of --clear, --migrate-schema, --import, --verify, or --reload-master-projects"
        )

    if args.clear:
        confirm = input(
            "[WARNING] This will drop and recreate the entire database\n"
            'Please type "CONFIRM" if you want to proceed: '
        )
        if confirm == "CONFIRM":
            clear_db()
        else:
            logger.error("\nAborting!")
            exit

    if args.migrate_schema:
        migrate_schema_cmd()

    if args.reload_master_projects:
        reload_master_projects(args.data_dir)

    if args.do_import:
        import_all_data(args.data_dir)

    if args.verify:
        success = verify_data(args.data_dir)
        if not success:
            exit(1)


if __name__ == "__main__":
    main()
