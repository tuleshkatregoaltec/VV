"""Source registry for Holocron."""

from holocron.sources.bayut.source import SOURCE as BAYUT_SOURCE
from holocron.sources.dld.source import SOURCE as DLD_SOURCE
from holocron.sources.dxbi.source import SOURCE as DXBI_SOURCE
from holocron.sources.geo.source import SOURCE as GEO_SOURCE
from holocron.sources.gis.source import SOURCE as GIS_SOURCE

SOURCES = [BAYUT_SOURCE, DLD_SOURCE, DXBI_SOURCE, GEO_SOURCE, GIS_SOURCE]
SOURCES_BY_NAME = {source.name: source for source in SOURCES}
