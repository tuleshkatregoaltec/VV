"""Seed the stored assessment with hand-built assessed rows."""

from app.crm import owner_store


async def install_rows(db, monkeypatch, rows, *, organization_id="org"):
    """Publish ``rows`` as the tenant's current assessment, as a build would after assessing."""

    async def tokens(_db, _organization_id):
        return "test-revision", "test-evidence"

    monkeypatch.setattr(owner_store, "_tokens", tokens)
    await owner_store.store_assessed_rows(
        db.bind, organization_id, rows, revision="test-revision", warehouse="test-evidence"
    )
