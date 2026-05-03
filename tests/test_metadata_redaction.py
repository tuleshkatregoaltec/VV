import json

import pytest

from holocron.platform.metadata import safe_config_metadata
from holocron.sources.bay_listings.source import BayutListingsConfig
from holocron.sources.bay_locations.source import BayutLocationsConfig
from holocron.sources.bay_transactions.source import BayutTransactionsConfig
from holocron.sources.dda.source import DdaConfig
from holocron.sources.dld.source import DldConfig
from holocron.sources.dxbi.source import DxbiConfig
from holocron.sources.reelly_supply.source import ReellySupplyConfig


@pytest.mark.parametrize(
    ("config", "secret_values", "redacted_keys"),
    [
        (
            BayutLocationsConfig(api_key="bay-locations-secret"),
            ("bay-locations-secret",),
            ("api_key",),
        ),
        (
            BayutListingsConfig(api_key="bay-listings-secret"),
            ("bay-listings-secret",),
            ("api_key",),
        ),
        (
            BayutTransactionsConfig(api_key="bay-transactions-secret"),
            ("bay-transactions-secret",),
            ("api_key",),
        ),
        (
            DldConfig(consumer_id="dld-consumer-secret"),
            ("dld-consumer-secret",),
            ("consumer_id",),
        ),
        (
            DxbiConfig(
                storage_state_path="/tmp/dxbi-storage-state.json",
                twocaptcha_api_key="captcha-secret",
            ),
            ("/tmp/dxbi-storage-state.json", "captcha-secret"),
            ("storage_state_path", "twocaptcha_api_key"),
        ),
        (
            ReellySupplyConfig(email="agent@example.com", password="reelly-password"),
            ("reelly-password",),
            ("password",),
        ),
        (DdaConfig(concurrency=2), (), ()),
    ],
)
def test_source_config_metadata_redacts_sensitive_values(
    config: object,
    secret_values: tuple[str, ...],
    redacted_keys: tuple[str, ...],
) -> None:
    metadata = safe_config_metadata(config)
    serialized = json.dumps(metadata, sort_keys=True)

    for secret_value in secret_values:
        assert secret_value not in serialized
    for key in redacted_keys:
        assert metadata[key] == "***"

    if isinstance(config, DdaConfig):
        assert metadata["concurrency"] == 2
