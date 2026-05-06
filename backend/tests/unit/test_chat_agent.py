from app.chat.agent import _area_search_text


def test_area_search_text_handles_parenthetical_jvc_alias():
    assert _area_search_text("Jumeirah Village Circle (JVC)") == "Jumeirah Village Circle"


def test_area_search_text_handles_common_initialisms():
    assert _area_search_text("JVC") == "Jumeirah Village Circle"
    assert _area_search_text("JLT") == "Jumeirah Lakes Towers"
    assert _area_search_text("JBR") == "Jumeirah Beach Residence"
