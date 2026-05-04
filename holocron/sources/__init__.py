from holocron.sources.registry import SourceRegistry
from holocron.sources.bay_locations import SOURCE as BAY_LOCATIONS_SOURCE
from holocron.sources.bay_listings import SOURCE as BAY_LISTINGS_SOURCE
from holocron.sources.bay_transactions import SOURCE as BAY_TRANSACTIONS_SOURCE
from holocron.sources.dda import SOURCE as DDA_SOURCE
from holocron.sources.dld import SOURCE as DLD_SOURCE
from holocron.sources.dxbi import SOURCE as DXBI_SOURCE
from holocron.sources.pf_listings import SOURCE as PF_LISTINGS_SOURCE
from holocron.sources.pf_locations import SOURCE as PF_LOCATIONS_SOURCE
from holocron.sources.reelly_supply import SOURCE as REELLY_SUPPLY_SOURCE

registry = SourceRegistry()

registry.register(BAY_LOCATIONS_SOURCE)
registry.register(BAY_LISTINGS_SOURCE)
registry.register(BAY_TRANSACTIONS_SOURCE)
registry.register(DDA_SOURCE)
registry.register(DLD_SOURCE)
registry.register(DXBI_SOURCE)
registry.register(PF_LOCATIONS_SOURCE)
registry.register(PF_LISTINGS_SOURCE)
registry.register(REELLY_SUPPLY_SOURCE)

__all__ = [
    "BAY_LISTINGS_SOURCE",
    "BAY_LOCATIONS_SOURCE",
    "BAY_TRANSACTIONS_SOURCE",
    "DDA_SOURCE",
    "DLD_SOURCE",
    "DXBI_SOURCE",
    "PF_LISTINGS_SOURCE",
    "PF_LOCATIONS_SOURCE",
    "REELLY_SUPPLY_SOURCE",
    "registry",
]
