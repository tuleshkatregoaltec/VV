"""Source registry for Holocron."""

from holocron.sources.bayut.source import SOURCE as BAYUT_SOURCE
from holocron.sources.dda.source import SOURCE as DDA_SOURCE
from holocron.sources.dld.source import SOURCE as DLD_SOURCE
from holocron.sources.dxbi.source import SOURCE as DXBI_SOURCE
from holocron.sources.dxbi_transactions.source import SOURCE as DXBI_TRANSACTIONS_SOURCE
from holocron.sources.geo.source import SOURCE as GEO_SOURCE
from holocron.sources.pf_locations.source import SOURCE as PF_LOCATIONS_SOURCE
from holocron.sources.pf_transactions.source import SOURCE as PF_TRANSACTIONS_SOURCE

SOURCES = [
    BAYUT_SOURCE,
    DDA_SOURCE,
    DLD_SOURCE,
    DXBI_SOURCE,
    DXBI_TRANSACTIONS_SOURCE,
    GEO_SOURCE,
    PF_LOCATIONS_SOURCE,
    PF_TRANSACTIONS_SOURCE,
]
SOURCES_BY_NAME = {source.name: source for source in SOURCES}
