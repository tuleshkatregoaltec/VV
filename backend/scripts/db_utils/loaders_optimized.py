from pathlib import Path
import logging

import pandas as pd
import numpy as np
from sqlmodel import Session, select, func
from tqdm import tqdm

from backend.app.database import engine
from backend.app.models import (
    Unit,
    Transaction,
    RentContract,
)

from backend.scripts.db_utils.loaders import DataLoader as OriginalDataLoader

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50000


def vectorized_clean_string(series: pd.Series) -> pd.Series:
    """Vectorized string cleaning"""
    if series.empty:
        return series
    return series.str.strip().replace('', None).where(series.notna(), None)


def vectorized_parse_int(series: pd.Series) -> pd.Series:
    """Vectorized int parsing"""
    if series.empty:
        return series
    return pd.to_numeric(series, errors='coerce').astype('Int64').where(series.notna(), None)


def vectorized_parse_decimal(series: pd.Series) -> pd.Series:
    """Vectorized decimal parsing"""
    if series.empty:
        return series
    return pd.to_numeric(series, errors='coerce').where(series.notna(), None)


def vectorized_parse_date(series: pd.Series) -> pd.Series:
    """Vectorized date parsing"""
    if series.empty:
        return series
    return pd.to_datetime(series, dayfirst=True, errors='coerce').dt.date.where(series.notna(), None)


def vectorized_parse_bool(series: pd.Series) -> pd.Series:
    """Vectorized bool parsing"""
    if series.empty:
        return series
    return series.astype('bool').where(series.notna(), None)


class DataLoader(OriginalDataLoader):
    """
    Optimized DataLoader - inherits from original, overrides only
    the 3 slow methods (Units, Transactions, Rent Contracts)
    """

    def load_units(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """OPTIMIZED: Units loader with vectorization and bulk insert"""
        from backend.scripts.db_utils.utils import rename_columns
        
        csv_total = self.get_csv_row_count("Units.csv")
        skip, existing, _ = self.skip_if_loaded(Unit, csv_total)

        if skip:
            logger.info(f"⊙ Units already loaded ({existing:,} records), skipping\n")
            return
        elif existing > 0:
            logger.info(f"⊙ Units resuming from {existing:,}/{csv_total:,} records [OPTIMIZED]...")
        else:
            logger.info("Loading Units [OPTIMIZED]...")

        existing_ids = set()
        if existing > 0:
            logger.info("  Pre-loading existing IDs...")
            with Session(self.engine) as session:
                result = session.exec(select(Unit.property_id)).all()
                existing_ids = set(result)
            logger.info(f"  Loaded {len(existing_ids):,} existing IDs")

        df_chunks = pd.read_csv(
            self.data_dir / "Units.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )

        total_inserted = 0
        total_chunks = (csv_total + batch_size - 1) // batch_size

        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df_chunks:
                chunk = rename_columns(chunk)

                chunk['property_id'] = vectorized_parse_int(chunk.get('property_id', pd.Series(dtype=str)))

                if existing_ids:
                    chunk = chunk[~chunk['property_id'].isin(existing_ids)]
                    if len(chunk) == 0:
                        pbar.update(1)
                        continue

                for col_name, parser in [
                    ('area_id', vectorized_parse_int), ('zone_id', vectorized_parse_int),
                    ('rooms', vectorized_parse_int), ('property_type_id', vectorized_parse_int),
                    ('property_sub_type_id', vectorized_parse_int),
                    ('parent_property_id', vectorized_parse_int),
                    ('grandparent_property_id', vectorized_parse_int),
                    ('project_id', vectorized_parse_int),
                    ('master_project_id', vectorized_parse_int),
                    ('land_type_id', vectorized_parse_int),
                    ('unit_balcony_area', vectorized_parse_decimal),
                    ('common_area', vectorized_parse_decimal),
                    ('actual_common_area', vectorized_parse_decimal),
                    ('actual_area', vectorized_parse_decimal),
                    ('creation_date', vectorized_parse_date),
                    ('is_free_hold', vectorized_parse_bool),
                    ('is_lease_hold', vectorized_parse_bool),
                    ('is_registered', vectorized_parse_bool),
                ]:
                    chunk[col_name] = parser(chunk.get(col_name, pd.Series(dtype=str)))

                str_cols = ['land_number', 'land_sub_number', 'building_number', 'unit_number',
                           'floor', 'rooms_ar', 'rooms_description', 'unit_parking_number',
                           'parking_allocation_type', 'parking_allocation_type_ar',
                           'parking_allocation_type_description', 'munc_zip_code',
                           'munc_number', 'parcel_id', 'pre_registration_number',
                           'land_type_ar', 'land_type']
                for col in str_cols:
                    if col in chunk.columns:
                        chunk[col] = vectorized_clean_string(chunk[col])

                record_dicts = chunk.replace({pd.NA: None, np.nan: None}).to_dict('records')

                if record_dicts:
                    with Session(self.engine) as session:
                        session.bulk_insert_mappings(Unit, record_dicts)
                        session.commit()

                    total_inserted += len(record_dicts)
                    for rd in record_dicts:
                        if rd.get('property_id'):
                            existing_ids.add(rd['property_id'])

                pbar.update(1)
                pbar.set_postfix({"total_loaded": f"{existing + total_inserted:,}"})

        final_count = self.get_table_count(Unit)
        logger.info(f"  ✓ Loaded {final_count:,} units total\n")

    def load_transactions(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """OPTIMIZED: Transactions loader"""
        from backend.scripts.db_utils.utils import rename_columns
        
        csv_total = self.get_csv_row_count("Transactions.csv")
        skip, existing, _ = self.skip_if_loaded(Transaction, csv_total)

        if skip:
            logger.info(f"⊙ Transactions already loaded ({existing:,} records), skipping\n")
            return
        elif existing > 0:
            logger.info(f"⊙ Transactions resuming from {existing:,}/{csv_total:,} records [OPTIMIZED]...")
        else:
            logger.info("Loading Transactions [OPTIMIZED]...")

        existing_ids = set()
        if existing > 0:
            logger.info("  Pre-loading existing transaction IDs...")
            with Session(self.engine) as session:
                result = session.exec(select(Transaction.transaction_id)).all()
                existing_ids = set(result)
            logger.info(f"  Loaded {len(existing_ids):,} existing IDs")

        df_chunks = pd.read_csv(
            self.data_dir / "Transactions.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )

        total_inserted = 0
        total_skipped = 0
        total_chunks = (csv_total + batch_size - 1) // batch_size

        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df_chunks:
                chunk = rename_columns(chunk)

                chunk['transaction_id'] = vectorized_clean_string(chunk.get('transaction_id', pd.Series(dtype=str)))

                initial_count = len(chunk)
                if existing_ids:
                    chunk = chunk[~chunk['transaction_id'].isin(existing_ids)]
                total_skipped += (initial_count - len(chunk))

                if len(chunk) == 0:
                    pbar.update(1)
                    pbar.set_postfix({"inserted": f"{total_inserted:,}", "skipped": f"{total_skipped:,}"})
                    continue

                for col_name, parser in [
                    ('procedure_id', vectorized_parse_int), ('trans_group_id', vectorized_parse_int),
                    ('property_type_id', vectorized_parse_int), ('property_sub_type_id', vectorized_parse_int),
                    ('reg_type_id', vectorized_parse_int), ('area_id', vectorized_parse_int),
                    ('no_of_parties_role_1', vectorized_parse_int), ('no_of_parties_role_2', vectorized_parse_int),
                    ('no_of_parties_role_3', vectorized_parse_int),
                    ('instance_date', vectorized_parse_date), ('has_parking', vectorized_parse_bool),
                    ('procedure_area', vectorized_parse_decimal), ('actual_worth', vectorized_parse_decimal),
                    ('meter_sale_price', vectorized_parse_decimal), ('rent_value', vectorized_parse_decimal),
                    ('meter_rent_price', vectorized_parse_decimal),
                ]:
                    chunk[col_name] = parser(chunk.get(col_name, pd.Series(dtype=str)))

                str_cols = ['trans_group_ar', 'trans_group_en', 'procedure_name_ar', 'procedure_name_en',
                           'property_type_ar', 'property_type_en', 'property_sub_type_ar', 'property_sub_type_en',
                           'property_usage_ar', 'property_usage_en', 'reg_type_ar', 'reg_type_en',
                           'area_name_ar', 'area_name_en', 'building_name_ar', 'building_name_en',
                           'project_number', 'project_name_ar', 'project_name_en',
                           'master_project_ar', 'master_project_en', 'nearest_landmark_ar', 'nearest_landmark_en',
                           'nearest_metro_ar', 'nearest_metro_en', 'nearest_mall_ar', 'nearest_mall_en',
                           'rooms_ar', 'rooms_en']
                for col in str_cols:
                    if col in chunk.columns:
                        chunk[col] = vectorized_clean_string(chunk[col])

                record_dicts = chunk.replace({pd.NA: None, np.nan: None}).to_dict('records')
                for rd in record_dicts:
                    rd['trans_group'] = rd.pop('trans_group_en', None)
                    rd['procedure_name'] = rd.pop('procedure_name_en', None)
                    rd['property_type'] = rd.pop('property_type_en', None)
                    rd['property_sub_type'] = rd.pop('property_sub_type_en', None)
                    rd['property_usage'] = rd.pop('property_usage_en', None)
                    rd['reg_type'] = rd.pop('reg_type_en', None)
                    rd['area_name'] = rd.pop('area_name_en', None)
                    rd['building_name'] = rd.pop('building_name_en', None)
                    rd['project_name'] = rd.pop('project_name_en', None)
                    rd['master_project'] = rd.pop('master_project_en', None)
                    rd['nearest_landmark'] = rd.pop('nearest_landmark_en', None)
                    rd['nearest_metro'] = rd.pop('nearest_metro_en', None)
                    rd['nearest_mall'] = rd.pop('nearest_mall_en', None)
                    rd['rooms_description'] = rd.pop('rooms_en', None)

                if record_dicts:
                    with Session(self.engine) as session:
                        session.bulk_insert_mappings(Transaction, record_dicts)
                        session.commit()

                    total_inserted += len(record_dicts)
                    for rd in record_dicts:
                        if rd.get('transaction_id'):
                            existing_ids.add(rd['transaction_id'])

                pbar.update(1)
                pbar.set_postfix({"inserted": f"{total_inserted:,}", "skipped": f"{total_skipped:,}"})

        final_count = self.get_table_count(Transaction)
        logger.info(f"  ✓ Loaded {final_count:,} transactions total ({total_skipped:,} skipped)\n")

    def load_rent_contracts(self, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        """OPTIMIZED: Rent contracts loader"""
        from backend.scripts.db_utils.utils import rename_columns
        
        csv_total = self.get_csv_row_count("Rent_Contracts.csv")
        skip, existing, _ = self.skip_if_loaded(RentContract, csv_total)

        if skip:
            logger.info(f"⊙ Rent Contracts already loaded ({existing:,} records), skipping\n")
            return
        elif existing > 0:
            logger.info(f"⊙ Rent Contracts resuming from {existing:,}/{csv_total:,} records [OPTIMIZED]...")
        else:
            logger.info("Loading Rent Contracts [OPTIMIZED]...")

        existing_keys = set()
        if existing > 0:
            logger.info("  Pre-loading existing contract keys...")
            with Session(self.engine) as session:
                result = session.exec(select(RentContract.contract_id, RentContract.line_number)).all()
                existing_keys = set(result)
            logger.info(f"  Loaded {len(existing_keys):,} existing keys")

        df_chunks = pd.read_csv(
            self.data_dir / "Rent_Contracts.csv",
            chunksize=batch_size,
            low_memory=False,
            dtype=str,
        )

        total_inserted = 0
        total_skipped = 0
        total_chunks = (csv_total + batch_size - 1) // batch_size

        with tqdm(total=total_chunks, desc="  Processing batches", unit="batch") as pbar:
            for chunk in df_chunks:
                chunk = rename_columns(chunk)

                chunk['contract_id'] = vectorized_clean_string(chunk.get('contract_id', pd.Series(dtype=str)))
                chunk['line_number'] = vectorized_parse_int(chunk.get('line_number', pd.Series(dtype=str)))

                initial_count = len(chunk)
                if existing_keys:
                    mask = chunk.apply(lambda row: (row['contract_id'], row['line_number']) not in existing_keys, axis=1)
                    chunk = chunk[mask]
                total_skipped += (initial_count - len(chunk))

                if len(chunk) == 0:
                    pbar.update(1)
                    pbar.set_postfix({"inserted": f"{total_inserted:,}", "skipped": f"{total_skipped:,}"})
                    continue

                for col_name, parser in [
                    ('contract_reg_type_id', vectorized_parse_int), ('no_of_prop', vectorized_parse_int),
                    ('ejari_bus_property_type_id', vectorized_parse_int),
                    ('ejari_property_type_id', vectorized_parse_int),
                    ('ejari_property_sub_type_id', vectorized_parse_int),
                    ('area_id', vectorized_parse_int), ('tenant_type_id', vectorized_parse_int),
                    ('contract_start_date', vectorized_parse_date), ('contract_end_date', vectorized_parse_date),
                    ('is_free_hold', vectorized_parse_bool),
                    ('contract_amount', vectorized_parse_decimal), ('annual_amount', vectorized_parse_decimal),
                    ('actual_area', vectorized_parse_decimal),
                ]:
                    chunk[col_name] = parser(chunk.get(col_name, pd.Series(dtype=str)))

                str_cols = ['contract_reg_type_ar', 'contract_reg_type_en',
                           'ejari_bus_property_type_ar', 'ejari_bus_property_type_en',
                           'ejari_property_type_ar', 'ejari_property_type_en',
                           'ejari_property_sub_type_ar', 'ejari_property_sub_type_en',
                           'property_usage_ar', 'property_usage_en',
                           'project_number', 'project_name_ar', 'project_name_en',
                           'master_project_ar', 'master_project_en',
                           'area_name_ar', 'area_name_en',
                           'nearest_landmark_ar', 'nearest_landmark_en',
                           'nearest_metro_ar', 'nearest_metro_en',
                           'nearest_mall_ar', 'nearest_mall_en',
                           'tenant_type_ar', 'tenant_type_en']
                for col in str_cols:
                    if col in chunk.columns:
                        chunk[col] = vectorized_clean_string(chunk[col])

                # Convert and rename
                record_dicts = chunk.replace({pd.NA: None, np.nan: None}).to_dict('records')
                for rd in record_dicts:
                    rd['contract_reg_type'] = rd.pop('contract_reg_type_en', None)
                    rd['ejari_bus_property_type'] = rd.pop('ejari_bus_property_type_en', None)
                    rd['ejari_property_type'] = rd.pop('ejari_property_type_en', None)
                    rd['ejari_property_sub_type'] = rd.pop('ejari_property_sub_type_en', None)
                    rd['property_usage'] = rd.pop('property_usage_en', None)
                    rd['project_name'] = rd.pop('project_name_en', None)
                    rd['master_project'] = rd.pop('master_project_en', None)
                    rd['area_name'] = rd.pop('area_name_en', None)
                    rd['nearest_landmark'] = rd.pop('nearest_landmark_en', None)
                    rd['nearest_metro'] = rd.pop('nearest_metro_en', None)
                    rd['nearest_mall'] = rd.pop('nearest_mall_en', None)
                    rd['tenant_type'] = rd.pop('tenant_type_en', None)

                if record_dicts:
                    with Session(self.engine) as session:
                        session.bulk_insert_mappings(RentContract, record_dicts)
                        session.commit()

                    total_inserted += len(record_dicts)
                    for rd in record_dicts:
                        key = (rd.get('contract_id'), rd.get('line_number'))
                        if key[0] and key[1]:
                            existing_keys.add(key)

                pbar.update(1)
                pbar.set_postfix({"inserted": f"{total_inserted:,}", "skipped": f"{total_skipped:,}"})

        final_count = self.get_table_count(RentContract)
        logger.info(f"  ✓ Loaded {final_count:,} rent contracts total ({total_skipped:,} skipped)\n")
