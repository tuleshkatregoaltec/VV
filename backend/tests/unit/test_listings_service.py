from app.listings.service import _card_from_row


class Row:
    def __init__(self, data):
        self._mapping = data


def test_card_image_count_uses_available_imported_images():
    card = _card_from_row(
        Row(
            {
                "listing_id": "listing-1",
                "listing_mode": "sale",
                "title": "Test listing",
                "images": [
                    {"label": "missing image url"},
                    {"medium_url": "https://example.com/1.jpg"},
                    {"small_url": "https://example.com/2.jpg"},
                ],
                "image_count": 28,
                "agent": {},
                "broker": {},
                "floorplans": [],
            }
        )
    )

    assert card.primary_image_url == "https://example.com/1.jpg"
    assert card.image_count == 2
