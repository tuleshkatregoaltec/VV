"""Independent cache invalidation shared by owner import and read services."""

from app.crm.import_models import CrmOwnerRegistrySummary

_OWNER_SUMMARY_CACHE_TTL_SECONDS = 300
_owner_summary_cache: dict[tuple[str, int | None], tuple[float, CrmOwnerRegistrySummary]] = {}


def _invalidate_owner_summary_cache(organization_id: str) -> None:
    for key in [key for key in _owner_summary_cache if key[0] == organization_id]:
        _owner_summary_cache.pop(key, None)
