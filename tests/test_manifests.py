from holocron.platform.manifests import manifest_s3_key, raw_file_s3_key


def test_manifest_key_uses_source_scoped_raw_layout() -> None:
    assert manifest_s3_key(source="bay_transactions", run_id="run-1") == (
        "raw/source=bay_transactions/manifests/run-1.json"
    )


def test_raw_file_key_uses_extract_date_and_run_id_partitioning() -> None:
    assert (
        raw_file_s3_key(
            source="bay_transactions",
            extract_date="2026-03-31",
            run_id="run-1",
            file_name="sales.csv",
        )
        == "raw/source=bay_transactions/extract_date=2026-03-31/run_id=run-1/sales.csv"
    )
