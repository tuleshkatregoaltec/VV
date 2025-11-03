import logging
from pathlib import Path

import pandas as pd
from sqlmodel import Session, select, func
from tqdm import tqdm

from backend.app.database import engine
from backend.app.models import (
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
from backend.scripts.db_utils.utils import (
    clean_value,
    parse_date,
    parse_bool,
    parse_decimal,
    parse_int,
    parse_str_from_numeric,
    rename_columns,
    extract_lookup_from_files,
)

logger = logging.getLogger(__name__)

# Default batch size for chunked loading operations
DEFAULT_BATCH_SIZE = 10000


class DataLoader:
    """Handles loading data from CSV files into the database"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.engine = engine

    def get_table_count(self, model: type) -> int:
        """Get count of records in a table"""
        with Session(self.engine) as session:
            try:
                return session.exec(select(func.count()).select_from(model)).one()
            except:
                return 0

    def get_csv_row_count(self, filename: str) -> int:
        """Get total row count from CSV file"""
        return sum(1 for _ in open(self.data_dir / filename)) - 1

    def skip_if_loaded(
        self, model: type, expected_count: int | None = None
    ) -> tuple[bool, int, int | None]:
        """Check if table is already loaded and return skip status"""
        existing = self.get_table_count(model)
        if expected_count and existing >= expected_count:
            return True, existing, expected_count
        elif existing > 0 and not expected_count:
            return True, existing, None
        return False, existing, expected_count

    def load_areas(self) -> None:
        """Load areas from Lkp_Areas.csv"""
        skip, existing, _ = self.skip_if_loaded(Area)
        if skip:
            logger.info(f"⊙ Areas already loaded ({existing:,} records), skipping\n")
            return

        logger.info("Loading Areas...")
        df = pd.read_csv(self.data_dir / "Lkp_Areas.csv")
        df = rename_columns(df)

        records = [
            Area(
                area_id=parse_int(row["area_id"]),
                name_ar=clean_value(row.get("name_ar")),
                name=clean_value(row.get("name_en")),
                municipality_number=clean_value(row.get("municipality_number")),
            )
            for row in df.to_dict('records')
        ]

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} areas\n")

    def load_transaction_lookups(self) -> None:
        """Load transaction groups and procedures"""
        existing_groups = self.get_table_count(TransactionGroup)
        existing_procs = self.get_table_count(TransactionProcedure)
        if existing_groups > 0 and existing_procs > 0:
            logger.info(
                f"⊙ Transaction lookups already loaded ({existing_groups:,} groups, {existing_procs:,} procedures), skipping\n"
            )
            return

        logger.info("Loading Transaction Groups and Procedures...")

        proc_df = pd.read_csv(self.data_dir / "Lkp_Transaction_Procedures.csv")
        proc_df = rename_columns(proc_df)

        trans_df = pd.read_csv(self.data_dir / "Transactions.csv", nrows=10000)
        trans_df = rename_columns(trans_df)

        groups = (
            trans_df[["trans_group_id", "trans_group_ar", "trans_group_en"]]
            .drop_duplicates()
            .dropna()
        )
        group_records = []
        for row in groups.to_dict('records'):
            group_records.append(
                TransactionGroup(
                    group_id=parse_int(row["trans_group_id"]),
                    group_name_ar=clean_value(row["trans_group_ar"]),
                    group_name=clean_value(row["trans_group_en"]),
                )
            )

        with Session(self.engine) as session:
            session.add_all(group_records)
            session.commit()
        logger.info(f"  ✓ Loaded {len(group_records):,} transaction groups")

        seen_procedures = set()
        procedure_records = []
        for row in proc_df.to_dict('records'):
            proc_id = parse_int(row["procedure_id"])
            if proc_id and proc_id not in seen_procedures:
                procedure_records.append(
                    TransactionProcedure(
                        procedure_id=proc_id,
                        group_id=parse_int(row["group_id"]),
                        is_pre_registration=parse_bool(row.get("is_pre_registration")),
                        procedure_name_ar=clean_value(row["name_ar"]),
                        procedure_name=clean_value(row["name_en"]),
                    )
                )
                seen_procedures.add(proc_id)

        with Session(self.engine) as session:
            session.add_all(procedure_records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(procedure_records):,} transaction procedures\n")

    def load_property_types(self) -> None:
        """Extract unique property types from property files"""
        skip, existing, _ = self.skip_if_loaded(PropertyType)
        if skip:
            logger.info(
                f"⊙ Property types already loaded ({existing:,} records), skipping\n"
            )
            return

        logger.info("Loading Property Types...")

        types_dict = extract_lookup_from_files(
            data_dir=self.data_dir,
            files=["Land_Registry.csv", "Buildings.csv", "Units.csv"],
            columns=["property_type_id", "property_type_ar", "property_type_en"],
            id_column="property_type_id",
        )

        records = [
            PropertyType(
                property_type_id=type_id,
                property_type_ar=type_ar,
                property_type=type_en,
            )
            for type_id, (type_ar, type_en) in sorted(types_dict.items())
        ]

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} property types\n")

    def load_property_sub_types(self) -> None:
        """Extract unique property sub-types from property files"""
        skip, existing, _ = self.skip_if_loaded(PropertySubType)
        if skip:
            logger.info(
                f"⊙ Property sub-types already loaded ({existing:,} records), skipping\n"
            )
            return

        logger.info("Loading Property Sub-Types...")

        subtypes_dict = extract_lookup_from_files(
            data_dir=self.data_dir,
            files=["Land_Registry.csv", "Buildings.csv", "Units.csv"],
            columns=[
                "property_sub_type_id",
                "property_type_id",
                "property_sub_type_ar",
                "property_sub_type_en",
            ],
            id_column="property_sub_type_id",
        )

        records = [
            PropertySubType(
                property_sub_type_id=sub_type_id,
                property_type_id=type_id,
                property_sub_type_ar=sub_type_ar,
                property_sub_type=sub_type_en,
            )
            for sub_type_id, (type_id, sub_type_ar, sub_type_en) in sorted(
                subtypes_dict.items()
            )
        ]

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} property sub-types\n")

    def load_master_projects(self) -> None:
        """Extract unique master projects from property files"""
        skip, existing, _ = self.skip_if_loaded(MasterProject)
        if skip:
            logger.info(
                f"⊙ Master projects already loaded ({existing:,} records), skipping\n"
            )
            return

        logger.info("Loading Master Projects...")

        projects_dict = extract_lookup_from_files(
            data_dir=self.data_dir,
            files=["Land_Registry.csv", "Buildings.csv", "Units.csv"],
            columns=["master_project_id", "master_project_ar", "master_project_en"],
            id_column="master_project_id",
        )

        records = [
            MasterProject(
                master_project_id=proj_id,
                master_project_name_ar=proj_name_ar,
                master_project_name=proj_name_en,
            )
            for proj_id, (proj_name_ar, proj_name_en) in sorted(projects_dict.items())
        ]

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} master projects\n")

    def load_developers(self) -> None:
        """Load developers from Developers.csv"""
        existing = self.get_table_count(Developer)
        if existing > 0:
            logger.info(
                f"⊙ Developers already loaded ({existing:,} records), skipping\n"
            )
            return

        logger.info("Loading Developers...")
        df = pd.read_csv(self.data_dir / "Developers.csv")
        df = rename_columns(df)

        records = []
        for row in df.to_dict('records'):
            records.append(
                Developer(
                    developer_id=parse_int(row["developer_id"]),
                    participant_id=parse_int(row.get("participant_id")),
                    developer_number=parse_int(row["developer_number"]),
                    developer_name_ar=clean_value(row["developer_name_ar"]),
                    developer_name=clean_value(row["developer_name_en"]),
                    registration_date=parse_date(row.get("registration_date")),
                    license_source_id=parse_int(row.get("license_source_id")),
                    license_source_ar=clean_value(row.get("license_source_ar")),
                    license_source=clean_value(row.get("license_source_en")),
                    license_type_id=parse_int(row.get("license_type_id")),
                    license_type_ar=clean_value(row.get("license_type_ar")),
                    license_type=clean_value(row.get("license_type_en")),
                    license_number=clean_value(row.get("license_number")),
                    license_issue_date=parse_date(row.get("license_issue_date")),
                    license_expiry_date=parse_date(row.get("license_expiry_date")),
                    chamber_of_commerce_no=clean_value(
                        row.get("chamber_of_commerce_no")
                    ),
                    legal_status=clean_value(row.get("legal_status")),
                    legal_status_ar=clean_value(row.get("legal_status_ar")),
                    legal_status_description=clean_value(row.get("legal_status_en")),
                    webpage=clean_value(row.get("webpage")),
                    phone=clean_value(row.get("phone")),
                    fax=clean_value(row.get("fax")),
                )
            )

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} developers\n")

    def load_projects(self) -> None:
        """Load projects from Projects.csv"""
        existing = self.get_table_count(Project)
        if existing > 0:
            logger.info(f"⊙ Projects already loaded ({existing:,} records), skipping\n")
            return

        logger.info("Loading Projects...")
        df = pd.read_csv(self.data_dir / "Projects.csv")
        df = rename_columns(df)

        records = []
        for row in df.to_dict('records'):
            records.append(
                Project(
                    project_id=parse_int(row["project_id"]),
                    project_number=parse_int(row.get("project_number")),
                    project_name=clean_value(row["project_name"]),
                    developer_id=parse_int(row.get("developer_id")),
                    master_developer_id=parse_int(row.get("master_developer_id")),
                    project_start_date=parse_date(row.get("project_start_date")),
                    project_end_date=parse_date(row.get("project_end_date")),
                    project_type_id=parse_int(row.get("project_type_id")),
                    project_type_ar=clean_value(row.get("project_type_ar")),
                    project_classification_id=parse_int(
                        row.get("project_classification_id")
                    ),
                    project_classification_ar=clean_value(
                        row.get("project_classification_ar")
                    ),
                    escrow_agent_id=parse_int(row.get("escrow_agent_id")),
                    escrow_agent_name=clean_value(row.get("escrow_agent_name")),
                    project_status=clean_value(row.get("project_status")),
                    project_status_ar=clean_value(row.get("project_status_ar")),
                    percent_completed=parse_int(row.get("percent_completed")),
                    completion_date=parse_date(row.get("completion_date")),
                    cancellation_date=parse_date(row.get("cancellation_date")),
                    project_description_ar=clean_value(
                        row.get("project_description_ar")
                    ),
                    project_description=clean_value(row.get("project_description_en")),
                    property_id=parse_int(row.get("property_id")),
                    area_id=parse_int(row.get("area_id")),
                    zoning_authority_id=parse_int(row.get("zoning_authority_id")),
                    zoning_authority_ar=clean_value(row.get("zoning_authority_ar")),
                    zoning_authority=clean_value(row.get("zoning_authority_en")),
                    no_of_lands=parse_int(row.get("no_of_lands")),
                    no_of_buildings=parse_int(row.get("no_of_buildings")),
                    no_of_villas=parse_int(row.get("no_of_villas")),
                    no_of_units=parse_int(row.get("no_of_units")),
                )
            )

        with Session(self.engine) as session:
            session.add_all(records)
            session.commit()

        logger.info(f"  ✓ Loaded {len(records):,} projects\n")

    def load_land_registry(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """Load land registry from Land_Registry.csv"""
        csv_total = self.get_csv_row_count("Land_Registry.csv")
        skip, existing, _ = self.skip_if_loaded(LandRegistry, csv_total)

        if skip:
            logger.info(
                f"⊙ Land Registry already loaded ({existing:,} records), skipping\n"
            )
            return
        elif existing > 0:
            logger.info(
                f"⊙ Land Registry resuming from {existing:,}/{csv_total:,} records..."
            )
        else:
            logger.info("Loading Land Registry...")

        existing_ids = set()
        if existing > 0:
            with Session(self.engine) as session:
                result = session.exec(select(LandRegistry.property_id)).all()
                existing_ids = set(result)

        df = pd.read_csv(
            self.data_dir / "Land_Registry.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )
        total_inserted = 0
        batch_num = 0

        # Calculate total chunks for progress bar
        total_chunks = (csv_total + batch_size - 1) // batch_size
        
        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df:
                batch_num += 1
                chunk = rename_columns(chunk)

                records = []
                for row_idx, row in enumerate(chunk.to_dict('records')):
                    property_id = parse_int(row.get("property_id"))

                    if property_id is None:
                        property_id = -int(row_idx)

                    if property_id in existing_ids:
                        continue

                    records.append(
                        LandRegistry(
                            property_id=property_id,
                            area_id=parse_int(row.get("area_id")),
                            zone_id=parse_int(row.get("zone_id")),
                            land_number=parse_str_from_numeric(row.get("land_number")),
                            land_sub_number=parse_str_from_numeric(
                                row.get("land_sub_number")
                            ),
                            actual_area=parse_decimal(row.get("actual_area")),
                            property_type_id=parse_int(row.get("property_type_id")),
                            property_sub_type_id=parse_int(row.get("property_sub_type_id")),
                            parcel_id=parse_str_from_numeric(row.get("parcel_id")),
                            munc_zip_code=parse_str_from_numeric(row.get("munc_zip_code")),
                            munc_number=parse_str_from_numeric(row.get("munc_number")),
                            is_free_hold=parse_bool(row.get("is_free_hold")),
                            is_registered=parse_bool(row.get("is_registered")),
                            pre_registration_number=clean_value(
                                row.get("pre_registration_number")
                            ),
                            separated_from=parse_int(row.get("separated_from")),
                            separated_reference=parse_int(row.get("separated_reference")),
                            project_id=parse_int(row.get("project_id")),
                            master_project_id=parse_int(row.get("master_project_id")),
                            land_type_id=parse_int(row.get("land_type_id")),
                            land_type_ar=clean_value(row.get("land_type_ar")),
                            land_type=clean_value(row.get("land_type")),
                        )
                    )
                    existing_ids.add(property_id)

                if records:
                    with Session(self.engine) as session:
                        session.add_all(records)
                        session.commit()
                    total_inserted += len(records)

                pbar.update(1)
                pbar.set_postfix({"total_loaded": f"{existing + total_inserted:,}"})

        final_count = self.get_table_count(LandRegistry)
        logger.info(f"  ✓ Loaded {final_count:,} land parcels total\n")

    def load_buildings(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """Load buildings from Buildings.csv"""
        csv_total = self.get_csv_row_count("Buildings.csv")
        skip, existing, _ = self.skip_if_loaded(Building, csv_total)

        if skip:
            logger.info(
                f"⊙ Buildings already loaded ({existing:,} records), skipping\n"
            )
            return
        elif existing > 0:
            logger.info(
                f"⊙ Buildings resuming from {existing:,}/{csv_total:,} records..."
            )
        else:
            logger.info("Loading Buildings...")

        existing_ids = set()
        if existing > 0:
            with Session(self.engine) as session:
                result = session.exec(select(Building.property_id)).all()
                existing_ids = set(result)

        df = pd.read_csv(
            self.data_dir / "Buildings.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )
        total_inserted = 0
        batch_num = 0

        total_chunks = (csv_total + batch_size - 1) // batch_size
        
        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df:
                batch_num += 1
                chunk = rename_columns(chunk)

                records = []
                for row_idx, row in enumerate(chunk.to_dict('records')):
                    property_id = parse_int(row.get("property_id"))

                    if property_id is None:
                        property_id = -int(row_idx)

                    if property_id in existing_ids:
                        continue

                    records.append(
                        Building(
                            property_id=property_id,
                            area_id=parse_int(row.get("area_id")),
                            zone_id=parse_int(row.get("zone_id")),
                            land_number=parse_str_from_numeric(row.get("land_number")),
                            land_sub_number=parse_str_from_numeric(
                                row.get("land_sub_number")
                            ),
                            building_number=clean_value(row.get("building_number")),
                            floors=parse_int(row.get("floors")),
                            bld_levels=parse_int(row.get("bld_levels")),
                            rooms=parse_int(row.get("rooms")),
                            rooms_ar=clean_value(row.get("rooms_ar")),
                            rooms_description=clean_value(row.get("rooms_en")),
                            car_parks=parse_int(row.get("car_parks")),
                            common_area=parse_decimal(row.get("common_area")),
                            actual_common_area=parse_decimal(row.get("actual_common_area")),
                            built_up_area=parse_decimal(row.get("built_up_area")),
                            actual_area=parse_decimal(row.get("actual_area")),
                            shops=parse_int(row.get("shops")),
                            flats=parse_int(row.get("flats")),
                            offices=parse_int(row.get("offices")),
                            swimming_pools=parse_int(row.get("swimming_pools")),
                            elevators=parse_int(row.get("elevators")),
                            property_type_id=parse_int(row.get("property_type_id")),
                            property_sub_type_id=parse_int(row.get("property_sub_type_id")),
                            parent_property_id=parse_int(row.get("parent_property_id")),
                            creation_date=parse_date(row.get("creation_date")),
                            parcel_id=parse_str_from_numeric(row.get("parcel_id")),
                            is_free_hold=parse_bool(row.get("is_free_hold")),
                            is_lease_hold=parse_bool(row.get("is_lease_hold")),
                            is_registered=parse_bool(row.get("is_registered")),
                            pre_registration_number=clean_value(
                                row.get("pre_registration_number")
                            ),
                            project_id=parse_int(row.get("project_id")),
                            master_project_id=parse_int(row.get("master_project_id")),
                            land_type_id=parse_int(row.get("land_type_id")),
                            land_type_ar=clean_value(row.get("land_type_ar")),
                            land_type=clean_value(row.get("land_type")),
                        )
                    )
                    existing_ids.add(property_id)

                if records:
                    with Session(self.engine) as session:
                        session.add_all(records)
                        session.commit()
                    total_inserted += len(records)

                pbar.update(1)
                pbar.set_postfix({"total_loaded": f"{existing + total_inserted:,}"})

        final_count = self.get_table_count(Building)
        logger.info(f"  ✓ Loaded {final_count:,} buildings total\n")

    def load_units(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """Load units from Units.csv"""
        csv_total = self.get_csv_row_count("Units.csv")
        skip, existing, _ = self.skip_if_loaded(Unit, csv_total)

        if skip:
            logger.info(f"⊙ Units already loaded ({existing:,} records), skipping\n")
            return
        elif existing > 0:
            logger.info(f"⊙ Units resuming from {existing:,}/{csv_total:,} records...")
        else:
            logger.info("Loading Units...")

        existing_ids = set()
        if existing > 0:
            with Session(self.engine) as session:
                result = session.exec(select(Unit.property_id)).all()
                existing_ids = set(result)

        df = pd.read_csv(
            self.data_dir / "Units.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )
        total_inserted = 0
        batch_num = 0

        total_chunks = (csv_total + batch_size - 1) // batch_size
        
        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df:
                batch_num += 1
                chunk = rename_columns(chunk)

                records = []
                for row_idx, row in enumerate(chunk.to_dict('records')):
                    property_id = parse_int(row.get("property_id"))

                    if property_id is None:
                        property_id = -int(row_idx)

                    if property_id in existing_ids:
                        continue

                    records.append(
                        Unit(
                            property_id=property_id,
                            area_id=parse_int(row.get("area_id")),
                            zone_id=parse_int(row.get("zone_id")),
                            land_number=parse_str_from_numeric(row.get("land_number")),
                            land_sub_number=parse_str_from_numeric(
                                row.get("land_sub_number")
                            ),
                            building_number=clean_value(row.get("building_number")),
                            unit_number=clean_value(row.get("unit_number")),
                        floor=clean_value(row.get("floor")),
                        rooms=parse_int(row.get("rooms")),
                        rooms_ar=clean_value(row.get("rooms_ar")),
                        rooms_description=clean_value(row.get("rooms_en")),
                        unit_balcony_area=parse_decimal(row.get("unit_balcony_area")),
                        common_area=parse_decimal(row.get("common_area")),
                        actual_common_area=parse_decimal(row.get("actual_common_area")),
                        actual_area=parse_decimal(row.get("actual_area")),
                        unit_parking_number=clean_value(row.get("unit_parking_number")),
                        parking_allocation_type=clean_value(
                            row.get("parking_allocation_type")
                        ),
                        parking_allocation_type_ar=clean_value(
                            row.get("parking_allocation_type_ar")
                        ),
                        parking_allocation_type_description=clean_value(
                            row.get("parking_allocation_type_en")
                        ),
                        property_type_id=parse_int(row.get("property_type_id")),
                        property_sub_type_id=parse_int(row.get("property_sub_type_id")),
                        parent_property_id=parse_int(row.get("parent_property_id")),
                        grandparent_property_id=parse_int(
                            row.get("grandparent_property_id")
                        ),
                        creation_date=parse_date(row.get("creation_date")),
                        munc_zip_code=parse_str_from_numeric(row.get("munc_zip_code")),
                        munc_number=parse_str_from_numeric(row.get("munc_number")),
                        parcel_id=parse_str_from_numeric(row.get("parcel_id")),
                        is_free_hold=parse_bool(row.get("is_free_hold")),
                        is_lease_hold=parse_bool(row.get("is_lease_hold")),
                        is_registered=parse_bool(row.get("is_registered")),
                        pre_registration_number=clean_value(
                            row.get("pre_registration_number")
                        ),
                        project_id=parse_int(row.get("project_id")),
                        master_project_id=parse_int(row.get("master_project_id")),
                        land_type_id=parse_int(row.get("land_type_id")),
                        land_type_ar=clean_value(row.get("land_type_ar")),
                        land_type=clean_value(row.get("land_type")),
                    )
                )
                    existing_ids.add(property_id)

                if records:
                    with Session(self.engine) as session:
                        session.add_all(records)
                        session.commit()
                    total_inserted += len(records)

                pbar.update(1)
                pbar.set_postfix({"total_loaded": f"{existing + total_inserted:,}"})

        final_count = self.get_table_count(Unit)
        logger.info(f"  ✓ Loaded {final_count:,} units total\n")

    def load_transactions(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """Load transactions from Transactions.csv"""
        csv_total = self.get_csv_row_count("Transactions.csv")
        skip, existing, _ = self.skip_if_loaded(Transaction, csv_total)

        if skip:
            logger.info(
                f"⊙ Transactions already loaded ({existing:,} records), skipping\n"
            )
            return
        elif existing > 0:
            logger.info(
                f"⊙ Transactions resuming from {existing:,}/{csv_total:,} records..."
            )
        else:
            logger.info("Loading Transactions...")

        df = pd.read_csv(
            self.data_dir / "Transactions.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )
        total_inserted = 0
        skipped = 0
        batch_num = 0
        
        total_chunks = (csv_total + batch_size - 1) // batch_size
        
        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df:
                batch_num += 1
                chunk = rename_columns(chunk)

                records = []
                for row_idx, row in enumerate(chunk.to_dict('records')):
                    transaction_id = clean_value(row.get("transaction_id"))

                    if transaction_id is None:
                        transaction_id = f"MISSING_{row_idx}"

                    records.append(
                        Transaction(
                            transaction_id=transaction_id,
                            procedure_id=parse_int(row.get("procedure_id")),
                            trans_group_id=parse_int(row.get("trans_group_id")),
                            trans_group_ar=clean_value(row.get("trans_group_ar")),
                            trans_group=clean_value(row.get("trans_group_en")),
                            procedure_name_ar=clean_value(row.get("procedure_name_ar")),
                            procedure_name=clean_value(row.get("procedure_name_en")),
                            instance_date=parse_date(row.get("instance_date")),
                            property_type_id=parse_int(row.get("property_type_id")),
                            property_type_ar=clean_value(row.get("property_type_ar")),
                            property_type=clean_value(row.get("property_type_en")),
                            property_sub_type_id=parse_int(row.get("property_sub_type_id")),
                        property_sub_type_ar=clean_value(
                            row.get("property_sub_type_ar")
                        ),
                        property_sub_type=clean_value(row.get("property_sub_type_en")),
                        property_usage_ar=clean_value(row.get("property_usage_ar")),
                        property_usage=clean_value(row.get("property_usage_en")),
                        reg_type_id=parse_int(row.get("reg_type_id")),
                        reg_type_ar=clean_value(row.get("reg_type_ar")),
                        reg_type=clean_value(row.get("reg_type_en")),
                        area_id=parse_int(row.get("area_id")),
                        area_name_ar=clean_value(row.get("area_name_ar")),
                        area_name=clean_value(row.get("area_name_en")),
                        building_name_ar=clean_value(row.get("building_name_ar")),
                        building_name=clean_value(row.get("building_name_en")),
                        project_number=clean_value(row.get("project_number")),
                        project_name_ar=clean_value(row.get("project_name_ar")),
                        project_name=clean_value(row.get("project_name_en")),
                        master_project_ar=clean_value(row.get("master_project_ar")),
                        master_project=clean_value(row.get("master_project_en")),
                        nearest_landmark_ar=clean_value(row.get("nearest_landmark_ar")),
                        nearest_landmark=clean_value(row.get("nearest_landmark_en")),
                        nearest_metro_ar=clean_value(row.get("nearest_metro_ar")),
                        nearest_metro=clean_value(row.get("nearest_metro_en")),
                        nearest_mall_ar=clean_value(row.get("nearest_mall_ar")),
                        nearest_mall=clean_value(row.get("nearest_mall_en")),
                        rooms_ar=clean_value(row.get("rooms_ar")),
                        rooms_description=clean_value(row.get("rooms_en")),
                        has_parking=parse_bool(row.get("has_parking")),
                        procedure_area=parse_decimal(row.get("procedure_area")),
                        actual_worth=parse_decimal(row.get("actual_worth")),
                        meter_sale_price=parse_decimal(row.get("meter_sale_price")),
                        rent_value=parse_decimal(row.get("rent_value")),
                        meter_rent_price=parse_decimal(row.get("meter_rent_price")),
                        no_of_parties_role_1=parse_int(row.get("no_of_parties_role_1")),
                        no_of_parties_role_2=parse_int(row.get("no_of_parties_role_2")),
                        no_of_parties_role_3=parse_int(row.get("no_of_parties_role_3")),
                    )
                )

                if records:
                    with Session(self.engine) as session:
                        try:
                            session.add_all(records)
                            session.commit()
                            total_inserted += len(records)
                        except Exception as e:
                            session.rollback()
                            skipped += len(records)
                
                pbar.update(1)
                pbar.set_postfix({
                    "inserted": f"{total_inserted:,}",
                    "skipped": f"{skipped:,}",
                    "total": f"{existing + total_inserted:,}"
                })

        final_count = self.get_table_count(Transaction)
        if skipped > 0:
            logger.info(f"  ✓ Loaded {final_count:,} transactions total ({skipped:,} duplicates skipped)\n")
        else:
            logger.info(f"  ✓ Loaded {final_count:,} transactions total\n")

    def load_rent_contracts(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """Load rental contracts with composite key (contract_id, line_number)"""
        csv_total = self.get_csv_row_count("Rent_Contracts.csv")
        skip, existing, _ = self.skip_if_loaded(RentContract, csv_total)

        if skip:
            logger.info(
                f"⊙ Rent Contracts already loaded ({existing:,} records), skipping\n"
            )
            return
        elif existing > 0:
            logger.info(
                f"⊙ Rent Contracts resuming from {existing:,}/{csv_total:,} records..."
            )
        else:
            logger.info("Loading Rent Contracts...")

        df = pd.read_csv(
            self.data_dir / "Rent_Contracts.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )
        total_inserted = 0
        skipped = 0
        batch_num = 0
        
        total_chunks = (csv_total + batch_size - 1) // batch_size
        
        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df:
                batch_num += 1
                chunk = rename_columns(chunk)

                records = []
                for row_idx, row in enumerate(chunk.to_dict('records')):
                    contract_id = clean_value(row.get("contract_id"))
                    line_number = parse_int(row.get("line_number"))

                    if contract_id is None:
                        contract_id = f"MISSING_C_{row_idx}"
                    if line_number is None:
                        line_number = -1

                    records.append(
                        RentContract(
                            contract_id=contract_id,
                            line_number=line_number,
                            contract_reg_type_id=parse_int(row.get("contract_reg_type_id")),
                            contract_reg_type_ar=clean_value(
                                row.get("contract_reg_type_ar")
                            ),
                            contract_reg_type=clean_value(row.get("contract_reg_type_en")),
                            contract_start_date=parse_date(row.get("contract_start_date")),
                            contract_end_date=parse_date(row.get("contract_end_date")),
                            contract_amount=parse_decimal(row.get("contract_amount")),
                            annual_amount=parse_decimal(row.get("annual_amount")),
                            no_of_prop=parse_int(row.get("no_of_prop")),
                        is_free_hold=parse_bool(row.get("is_free_hold")),
                        ejari_bus_property_type_id=parse_int(
                            row.get("ejari_bus_property_type_id")
                        ),
                        ejari_bus_property_type_ar=clean_value(
                            row.get("ejari_bus_property_type_ar")
                        ),
                        ejari_bus_property_type=clean_value(
                            row.get("ejari_bus_property_type_en")
                        ),
                        ejari_property_type_id=parse_int(
                            row.get("ejari_property_type_id")
                        ),
                        ejari_property_type=clean_value(
                            row.get("ejari_property_type_en")
                        ),
                        ejari_property_type_ar=clean_value(
                            row.get("ejari_property_type_ar")
                        ),
                        ejari_property_sub_type_id=parse_int(
                            row.get("ejari_property_sub_type_id")
                        ),
                        ejari_property_sub_type=clean_value(
                            row.get("ejari_property_sub_type_en")
                        ),
                        ejari_property_sub_type_ar=clean_value(
                            row.get("ejari_property_sub_type_ar")
                        ),
                        property_usage=clean_value(row.get("property_usage_en")),
                        property_usage_ar=clean_value(row.get("property_usage_ar")),
                        project_number=clean_value(row.get("project_number")),
                        project_name_ar=clean_value(row.get("project_name_ar")),
                        project_name=clean_value(row.get("project_name_en")),
                        master_project_ar=clean_value(row.get("master_project_ar")),
                        master_project=clean_value(row.get("master_project_en")),
                        area_id=parse_int(row.get("area_id")),
                        area_name_ar=clean_value(row.get("area_name_ar")),
                        area_name=clean_value(row.get("area_name_en")),
                        actual_area=parse_decimal(row.get("actual_area")),
                        nearest_landmark_ar=clean_value(row.get("nearest_landmark_ar")),
                        nearest_landmark=clean_value(row.get("nearest_landmark_en")),
                        nearest_metro_ar=clean_value(row.get("nearest_metro_ar")),
                        nearest_metro=clean_value(row.get("nearest_metro_en")),
                        nearest_mall_ar=clean_value(row.get("nearest_mall_ar")),
                        nearest_mall=clean_value(row.get("nearest_mall_en")),
                        tenant_type_id=parse_int(row.get("tenant_type_id")),
                        tenant_type_ar=clean_value(row.get("tenant_type_ar")),
                        tenant_type=clean_value(row.get("tenant_type_en")),
                    )
                )

                if records:
                    with Session(self.engine) as session:
                        try:
                            session.add_all(records)
                            session.commit()
                            total_inserted += len(records)
                        except Exception as e:
                            session.rollback()
                            skipped += len(records)
                
                pbar.update(1)
                pbar.set_postfix({
                    "inserted": f"{total_inserted:,}",
                    "skipped": f"{skipped:,}",
                    "total": f"{existing + total_inserted:,}"
                })

        final_count = self.get_table_count(RentContract)
        if skipped > 0:
            logger.info(f"  ✓ Loaded {final_count:,} rent contracts total ({skipped:,} duplicates skipped)\n")
        else:
            logger.info(f"  ✓ Loaded {final_count:,} rent contracts total\n")
