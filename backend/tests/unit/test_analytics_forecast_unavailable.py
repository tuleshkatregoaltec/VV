"""The project forecast says it is not available instead of answering an empty series.

DXBI's records hold no delivery schedule to anchor a price curve on, and the DLD off-plan curve
it used is frozen: an empty list read as "no forecast data for this project".
"""

from app.analytics import service


async def test_forecast_is_explicitly_unavailable():
    response = await service.get_project_forecast("Binghatti Hills", 365)

    assert response.available is False
    assert response.data == []
    assert "not available" in response.unavailable_reason
