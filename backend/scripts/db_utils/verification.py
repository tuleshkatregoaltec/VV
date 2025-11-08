"""Data verification utilities."""

import logging
from pathlib import Path
import pandas as pd
from sqlmodel import Session, select
from sqlalchemy import func

from backend.app.database import engine
from backend.scripts.db_utils.utils import rename_columns

logger = logging.getLogger(__name__)


def count_csv_rows(data_dir: Path, csv_file: str) -> int:
    """Count total rows in a CSV file (excluding header)."""
    return sum(1 for _ in open(data_dir / csv_file)) - 1


def get_db_count(session: Session, model) -> int:
    """Get count of records in a database table."""
    return session.exec(select(func.count()).select_from(model)).one()


def count_unique_areas(data_dir: Path) -> int:
    """Count unique areas from Lkp_Areas.csv."""
    logger.info("  Analyzing Areas from Lkp_Areas.csv...")
    df = pd.read_csv(data_dir / "Lkp_Areas.csv")
    return len(df)


def count_unique_transaction_groups(data_dir: Path) -> int:
    """Count unique transaction groups from Transactions.csv."""
    logger.info("  Analyzing Transaction Groups from Transactions.csv...")
    df = pd.read_csv(
        data_dir / "Transactions.csv",
        usecols=["trans_group_id", "trans_group_ar", "trans_group_en"],
    )
    df = rename_columns(df)
    unique_groups = (
        df[["trans_group_id", "trans_group_ar", "trans_group_en"]]
        .drop_duplicates()
        .dropna()
    )
    return len(unique_groups)


def count_unique_transaction_procedures(data_dir: Path) -> int:
    """Count unique procedures from Lkp_Transaction_Procedures.csv."""
    logger.info(
        "  Analyzing Transaction Procedures from Lkp_Transaction_Procedures.csv..."
    )
    df = pd.read_csv(data_dir / "Lkp_Transaction_Procedures.csv")
    return df["procedure_id"].nunique()


def count_unique_property_types(data_dir: Path) -> int:
    """Count unique property types across Land_Registry, Buildings, and Units."""
    logger.info(
        "  Analyzing Property Types from Land_Registry.csv, Buildings.csv, Units.csv..."
    )
    types = set()

    for csv_file in ["Land_Registry.csv", "Buildings.csv", "Units.csv"]:
        df = pd.read_csv(data_dir / csv_file, low_memory=False)
        df = rename_columns(df)

        if "property_type_id" in df.columns:
            for val in df["property_type_id"].dropna().unique():
                try:
                    types.add(int(float(val)))
                except:
                    pass

    return len(types)


def count_unique_property_sub_types(data_dir: Path) -> int:
    """Count unique property sub-types across Land_Registry, Buildings, and Units."""
    logger.info(
        "  Analyzing Property Sub-Types from Land_Registry.csv, Buildings.csv, Units.csv..."
    )
    sub_types = set()

    for csv_file in ["Land_Registry.csv", "Buildings.csv", "Units.csv"]:
        df = pd.read_csv(data_dir / csv_file, low_memory=False)
        df = rename_columns(df)

        if "property_sub_type_id" in df.columns:
            for val in df["property_sub_type_id"].dropna().unique():
                try:
                    sub_types.add(int(float(val)))
                except:
                    pass

    return len(sub_types)


def count_unique_master_projects(data_dir: Path) -> int:
    """Count unique master projects from Land_Registry, Buildings, and Units."""
    logger.info(
        "  Analyzing Master Projects from Land_Registry.csv, Buildings.csv, Units.csv..."
    )
    projects = set()

    for csv_file in ["Land_Registry.csv", "Buildings.csv", "Units.csv"]:
        df = pd.read_csv(data_dir / csv_file, low_memory=False)
        df = rename_columns(df)

        if "master_project_id" in df.columns:
            for val in df["master_project_id"].dropna().unique():
                try:
                    projects.add(int(float(val)))
                except:
                    pass

    return len(projects)


def verify_import(data_dir: Path, models: dict) -> bool:
    """Verify data import by comparing CSV counts with database counts."""
    logger.info("\n" + "=" * 70)
    logger.info(" DATA IMPORT VERIFICATION")
    logger.info("=" * 70 + "\n")

    logger.info("Calculating expected row counts from CSV files...")
    logger.info("-" * 70)

    with Session(engine) as session:
        checks = []

        logger.info("\nLookup Tables:")
        checks.append(
            (
                "Areas",
                count_unique_areas(data_dir),
                get_db_count(session, models["Area"]),
            )
        )
        checks.append(
            (
                "Transaction Groups",
                count_unique_transaction_groups(data_dir),
                get_db_count(session, models["TransactionGroup"]),
            )
        )
        checks.append(
            (
                "Transaction Procedures",
                count_unique_transaction_procedures(data_dir),
                get_db_count(session, models["TransactionProcedure"]),
            )
        )
        checks.append(
            (
                "Property Types",
                count_unique_property_types(data_dir),
                get_db_count(session, models["PropertyType"]),
            )
        )
        checks.append(
            (
                "Property Sub-Types",
                count_unique_property_sub_types(data_dir),
                get_db_count(session, models["PropertySubType"]),
            )
        )
        checks.append(
            (
                "Master Projects",
                count_unique_master_projects(data_dir),
                get_db_count(session, models["MasterProject"]),
            )
        )

        logger.info("\nEntity Tables:")
        checks.append(
            (
                "Developers",
                count_csv_rows(data_dir, "Developers.csv"),
                get_db_count(session, models["Developer"]),
            )
        )
        checks.append(
            (
                "Projects",
                count_csv_rows(data_dir, "Projects.csv"),
                get_db_count(session, models["Project"]),
            )
        )

        logger.info("\nProperty Hierarchy:")
        checks.append(
            (
                "Land Registry",
                count_csv_rows(data_dir, "Land_Registry.csv"),
                get_db_count(session, models["LandRegistry"]),
            )
        )
        checks.append(
            (
                "Buildings",
                count_csv_rows(data_dir, "Buildings.csv"),
                get_db_count(session, models["Building"]),
            )
        )
        checks.append(
            (
                "Units",
                count_csv_rows(data_dir, "Units.csv"),
                get_db_count(session, models["Unit"]),
            )
        )

        logger.info("\nTransactions:")
        checks.append(
            (
                "Transactions",
                count_csv_rows(data_dir, "Transactions.csv"),
                get_db_count(session, models["Transaction"]),
            )
        )

        logger.info("\nRent Contracts:")
        checks.append(
            (
                "Rent Contracts",
                count_csv_rows(data_dir, "Rent_Contracts.csv"),
                get_db_count(session, models["RentContract"]),
            )
        )

    logger.info("\n" + "=" * 70)
    logger.info(" VERIFICATION RESULTS")
    logger.info("=" * 70 + "\n")

    logger.info(
        f"{'Table':<25} {'Expected':>12} {'Actual':>12} {'Diff':>12} {'Status':>10}"
    )
    logger.info("-" * 70)

    total_expected = 0
    total_actual = 0
    discrepancies = []

    for table_name, expected, actual in checks:
        diff = actual - expected
        total_expected += expected
        total_actual += actual

        if diff == 0:
            status = "✓ OK"
        elif diff < 0:
            status = "✗ MISSING"
            discrepancies.append((table_name, expected, actual, diff))
        else:
            status = "⚠ EXTRA"
            discrepancies.append((table_name, expected, actual, diff))

        logger.info(
            f"{table_name:<25} {expected:>12,} {actual:>12,} {diff:>+12,} {status:>10}"
        )

    logger.info("-" * 70)
    logger.info(
        f"{'TOTAL':<25} {total_expected:>12,} {total_actual:>12,} {total_actual - total_expected:>+12,}"
    )

    logger.info("\n" + "=" * 70)
    if not discrepancies:
        logger.info(" ✓ ALL TABLES MATCH EXPECTED COUNTS!")
    else:
        logger.info(f" ⚠  {len(discrepancies)} TABLE(S) WITH DISCREPANCIES")
        logger.info("=" * 70)
        logger.info("\nDiscrepancy Details:")
        for table_name, expected, actual, diff in discrepancies:
            logger.info(f"\n  {table_name}:")
            logger.info(f"    Expected:  {expected:,} rows")
            logger.info(f"    Actual:    {actual:,} rows")
            logger.info(
                f"    Missing:   {abs(diff):,} rows"
                if diff < 0
                else f"    Extra:     {diff:,} rows"
            )

            if diff < 0:
                percentage_lost = (abs(diff) / expected * 100) if expected > 0 else 0
                logger.info(f"    Data Loss: {percentage_lost:.2f}%")

        logger.info("\n💡 Check the import error log for details on failed insertions.")

    logger.info("=" * 70 + "\n")

    return len(discrepancies) == 0
