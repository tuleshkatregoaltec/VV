"""One place resolver: sheet labels and DXBI / Transactions events share one key space."""

import pytest

from app.crm.owner_places import (
    Place,
    PlaceIndex,
    clean_label,
    load_place_aliases,
    place_key,
)

BUILDINGS = [
    {
        "name_key": "navitastowere",
        "community_key": "damachills2",
        "project_key": "navitas",
        "building_id": "b1",
    },
    {"name_key": "alfurjan", "community_key": "alfurjan", "project_key": "", "building_id": "b2"},
    {"name_key": "quortaj", "community_key": "alfurjan", "project_key": "", "building_id": "b5"},
    {"name_key": "quortaj2", "community_key": "alfurjan", "project_key": "", "building_id": "b6"},
    {
        "name_key": "ruba",
        "community_key": "arabianranches3",
        "project_key": "",
        "building_id": "b7",
    },
    {"name_key": "sun", "community_key": "arabianranches3", "project_key": "", "building_id": "b8"},
    {"name_key": "zeta", "community_key": "dubaimarina", "project_key": "", "building_id": "b9"},
    {
        "name_key": "building4acw",
        "community_key": "alwasl",
        "project_key": "",
        "building_id": "b10",
    },
    {
        "name_key": "building4bcw",
        "community_key": "alwasl",
        "project_key": "",
        "building_id": "b11",
    },
    {"name_key": "building5cw", "community_key": "alwasl", "project_key": "", "building_id": "b12"},
    {"name_key": "vervetowera", "community_key": "alwasl", "project_key": "", "building_id": "b13"},
    {"name_key": "vervetowerb", "community_key": "alwasl", "project_key": "", "building_id": "b14"},
    {"name_key": "elo", "community_key": "damachills2", "project_key": "elo", "building_id": "b15"},
    {
        "name_key": "elo2",
        "community_key": "damachills2",
        "project_key": "elo",
        "building_id": "b16",
    },
    {
        "name_key": "viridisa",
        "community_key": "damachills2",
        "project_key": "viridis",
        "building_id": "b17",
    },
    {"name_key": "tower1", "community_key": "dubaimarina", "project_key": "", "building_id": "b3"},
    {"name_key": "tower1", "community_key": "jlt", "project_key": "", "building_id": "b4"},
]
PROJECT_ALIASES: dict[str, str] = {}
MASTER_ALIASES = {"akoyaoxygen": "Damac Hills 2"}


@pytest.fixture
def index():
    return PlaceIndex(BUILDINGS, PROJECT_ALIASES, MASTER_ALIASES)


def sheet(index, **fields):
    place = index.source_place(fields)
    assert place is not None, fields
    return place


def test_clean_label_drops_suffix_brackets_and_blanks():
    assert clean_label("NAVITAS ( E )@AKOYA OXYGEN") == "NAVITAS E"
    assert clean_label("  Damac   Hills (2) ") == "Damac Hills 2"
    assert [clean_label(v) for v in ("#REF!", 0, "null", None, "  ")] == [""] * 5


def test_clean_label_never_strips_numbers():
    # Repairing the autofill run is the parser's job; stripping 7528 would give Damac Hills (1).
    assert clean_label("DAMAC HILLS 7528") == "DAMAC HILLS 7528"


def test_place_key_roman_numerals_and_generic_words():
    assert place_key("Arabian Ranches lll") == "arabianranches3"
    assert place_key("Arabian Ranches III") == "arabianranches3"
    assert place_key("Damac Hills II") == "damachills2"
    assert place_key("The Residences Tower B") == "b"
    assert place_key("Navitas Tower E") == place_key("NAVITAS E") == "navitase"


def test_navitas_akoya_label_resolves(index):
    place = sheet(index, master_project="DAMAC HILLS 2", building_name="NAVITAS ( E )@AKOYA OXYGEN")
    assert (place.community, place.building) == ("damachills2", "navitase")
    event = index.event_place({"area_name": "Damac Hills 2", "building_name": "Navitas Tower E"})
    assert index.same_place(place, event)
    other_tower = index.event_place(
        {"area_name": "Damac Hills 2", "building_name": "Navitas Tower A"}
    )
    assert not index.same_place(place, other_tower)


def test_akoya_oxygen_alias_is_a_damac_hills_2_label(index):
    place = sheet(index, master_project="AKOYA OXYGEN")
    assert index.same_place(place, index.event_place({"area_name": "Damac Hills 2"}))


def test_legal_area_event_joins_community(index):
    event = index.event_place({"area_name": "Jabal Ali 1", "building_name": "Al Furjan"})
    assert event.community == "alfurjan" and event.building == ""
    assert index.same_place(sheet(index, master_project="Al Furjan"), event)


def test_ruba_alias(index):
    place = sheet(index, project_name="Arabian Ranches lll - Ruba")
    assert index.same_place(
        place, index.event_place({"area_name": "Arabian Ranches 3", "building_name": "Ruba"})
    )
    # Same community, other villa project: the project the sheet names must agree.
    assert not index.same_place(
        place, index.event_place({"area_name": "Arabian Ranches 3", "building_name": "Sun"})
    )


def test_liwan_is_not_arabian_ranches(index):
    place = sheet(index, project_name="Arabian Ranches III - SUN")
    event = index.event_place(
        {"area_name": "Liwan", "project_name": "Qpoint", "building_name": "Mazaya 19"}
    )
    assert not index.same_place(place, event)


def test_spreadsheet_noise_is_not_a_place(index):
    assert [clean_label(v) for v in ("#REF!", 0, "null")] == ["", "", ""]
    assert index.source_place({"master_project": "#REF!", "building_name": "null"}) is None
    # An autofill run the parser did not repair must never read as Damac Hills (1).
    unrepaired = sheet(index, master_project="DAMAC HILLS 7528")
    damac_hills_1 = index.event_place({"area_name": "Damac Hills"})
    assert not index.same_place(unrepaired, damac_hills_1)
    assert unrepaired.community != "damachills"


def test_damac_hills_numbers_are_different_communities(index):
    damac_hills_2 = sheet(index, master_project="Damac Hills 2")
    assert not index.same_place(damac_hills_2, index.event_place({"area_name": "Damac Hills"}))


def test_generic_building_needs_community(index):
    assert index.source_place({"building_name": "Tower 1"}) is None
    place = sheet(index, master_project="Dubai Marina", building_name="Tower 1")
    assert index.same_place(
        place, index.event_place({"area_name": "Dubai Marina", "building_name": "Tower 1"})
    )
    assert not index.same_place(
        place, index.event_place({"area_name": "Jumeirah Lake Towers", "building_name": "Tower 1"})
    )


def test_listed_city_walk_buildings(index):
    place = sheet(
        index, master_project="City Walk", building_name="NO. 4A, NO.4B, NO.5 CITYWALK RESIDENTIAL"
    )
    for building in ("Building 4a (CW)", "Citywalk Residential Building 5", "Building 4b (CW)"):
        event = index.event_place({"area_name": "City Walk", "building_name": building})
        assert index.same_place(place, event), building
    for building in ("Building 6 (CW)", "Building 4 (CW)"):
        event = index.event_place({"area_name": "City Walk", "building_name": building})
        assert not index.same_place(place, event), building


def test_springs_is_not_ar3_spring(index):
    place = sheet(index, master_project="Emirates Living", project_name="Springs - 3")
    event = index.event_place({"area_name": "Arabian Ranches 3", "building_name": "Spring"})
    assert not index.same_place(place, event)


def test_partial_names_need_five_characters(index):
    short = sheet(index, master_project="Dubai Marina", building_name="Zeta")
    assert not index.same_place(
        short, index.event_place({"area_name": "Dubai Marina", "building_name": "Zeta Tower Plus"})
    )


def test_community_check_reads_project_label(index):
    place = sheet(index, master_project="Emirates Living", project_name="Emirates Hills")
    event = index.event_place(
        {"master_project": "Emirates Hills", "area_name": "Al Thanayah Fourth"}
    )
    assert index.same_place(place, event)


def test_unknown_communities_need_a_shared_name(index):
    # Nothing known on either side is not evidence of the same place.
    assert not index.same_place(Place("", "", ""), Place("", "", ""))


def test_packaged_aliases_are_loaded_with_the_akoya_row():
    projects, masters = load_place_aliases()
    assert masters[place_key("AKOYA OXYGEN")] == "Damac Hills 2"
    assert projects[place_key("GOLF TOWER")] == "Golf Towers"  # "tower" is generic: key is "golf"


def test_letter_tower_matches_with_or_without_the_community_in_its_name(index):
    # City Walk New / Until August row 752: sheet "Verve City Walk Tower B", DXBI "Verve Tower B".
    place = sheet(
        index,
        area_name="Al Wasl",
        master_project="City Walk",
        project_name="Verve",
        building_name="Verve City Walk Tower B",
    )
    verve = {"area_name": "City Walk", "project_name": "City Walk"}
    assert index.same_place(place, index.event_place({**verve, "building_name": "Verve Tower B"}))
    # The letter is the identity of the tower; another tower or another project is not it.
    assert not index.same_place(
        place, index.event_place({**verve, "building_name": "Verve Tower A"})
    )
    assert not index.same_place(
        place, index.event_place({**verve, "building_name": "Vida Tower B"})
    )


def test_plain_letter_tower_does_not_cross_projects(index):
    place = sheet(index, master_project="City Walk", building_name="Verve Tower B")
    other = index.event_place({"area_name": "City Walk", "building_name": "Vida Tower B"})
    assert not index.same_place(place, other)


def test_event_with_only_a_community_named_building_gets_that_community():
    # JVT old row 1678: DXBI filed the sale with a blank area and project, and the building
    # "Jumeirah Village Triangle (JVT)". The "(JVT)" suffix must not hide the community.
    jvt = PlaceIndex(
        [{"name_key": "alfurjan", "community_key": "jumeirahvillagetriangle", "project_key": ""}],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    event = jvt.event_place(
        {"area_name": "", "project_name": "", "building_name": "Jumeirah Village Triangle (JVT)"}
    )
    assert event.community == "jumeirahvillagetriangle" and event.building == ""
    place = sheet(jvt, master_project="Jumeirah Village Triangle")
    assert jvt.same_place(place, event)
    other = jvt.event_place({"area_name": "", "building_name": "Jumeirah Village Circle (JVC)"})
    assert not jvt.same_place(place, other)


def test_unknown_package_label_does_not_veto_a_known_building(index):
    # Furjan OLD row 21498: DLD's "ALFURJAN PACKAGE 4" is not an Analytics project or building.
    place = sheet(index, master_project="Al Furjan", project_name="ALFURJAN PACKAGE 4")
    quortaj = {"area_name": "Al Furjan", "project_name": "Quortaj", "building_name": "Quortaj"}
    assert index.same_place(place, index.event_place(quortaj))
    # The community gate stays: the same label in another community is not this place.
    elsewhere = {"area_name": "Dubai Marina", "building_name": "Quortaj"}
    assert not index.same_place(place, index.event_place(elsewhere))


def test_known_building_label_still_restricts(index):
    place = sheet(index, master_project="Al Furjan", building_name="Quortaj 2")
    quortaj = {"area_name": "Al Furjan", "project_name": "Quortaj", "building_name": "Quortaj"}
    quortaj_2 = {
        "area_name": "Al Furjan",
        "project_name": "Quortaj 2",
        "building_name": "Quortaj 2",
    }
    assert not index.same_place(place, index.event_place(quortaj))
    assert index.same_place(place, index.event_place(quortaj_2))


def test_unknown_building_label_does_not_veto_either(index):
    place = sheet(index, master_project="Al Furjan", building_name="Package 4")
    quortaj = {"area_name": "Al Furjan", "project_name": "Quortaj", "building_name": "Quortaj"}
    assert index.same_place(place, index.event_place(quortaj))


def test_project_named_like_the_community_is_not_a_name_restriction(index):
    # Furjan OLD row 7735: project "Al Furjan" says the community, not a project inside it.
    place = sheet(index, master_project="Al Furjan", project_name="Al Furjan")
    primero = {"area_name": "Al Furjan", "project_name": "Primero", "building_name": "Primero"}
    assert index.same_place(place, index.event_place(primero))


def test_explicit_building_designator_restricts_even_when_the_hierarchy_lacks_it(index):
    # City Walk row 2445: "Citywalk Residential Building 11B" is a building, known or not.
    place = sheet(
        index, master_project="City Walk", building_name="Citywalk Residential Building 11B"
    )
    walk = {"area_name": "City Walk"}
    assert index.same_place(
        place, index.event_place({**walk, "building_name": "Building 11b (CW)"})
    )
    assert not index.same_place(
        place, index.event_place({**walk, "building_name": "Building 12b (CW)"})
    )


# ---- v2c: community gate holes found in the v2b shadow run (real labels, no owner data) ------


@pytest.mark.parametrize(
    ("sheet_fields", "event"),
    [
        # JVT old 601: DLD master "The Villa", area Al Ruwayyah. "villa" sits inside the longer
        # "jumeirahvillagetriangle" but is not that community.
        (
            {"master_project": "Jumeirah Village Triangle"},
            {"master_project_en": "The Villa", "area_name_en": "Al Ruwayyah"},
        ),
        # JVT old 869: a legal area "Jumeirah" is not Jumeirah Village Triangle.
        (
            {"master_project": "Jumeirah Village Triangle"},
            {"area_name_en": "Jumeirah"},
        ),
        # Emirates Living 11690: DLD's "The Hills" (Emaar) is not "Emirates Hills".
        (
            {"master_project": "Emirates Living", "project_name": "Emirates Hills"},
            {
                "master_project_en": "The Lakes",
                "project_name_en": "The Hills",
                "building_name_en": "VIDA Residences 1 & 2",
                "area_name_en": "THE LAKES",
            },
        ),
        # Emirates Living 12363: "spring" (AR3 Spring) sits inside "springs3".
        (
            {"master_project": "Emirates Living", "project_name": "Springs - 3"},
            {
                "master_project_en": "Arabian Ranches 3",
                "project_name_en": "Arabian Ranches III - Spring",
                "building_name_en": "Spring",
                "area_name_en": "Wadi Al Safa 5",
            },
        ),
    ],
)
def test_a_community_label_inside_a_longer_one_is_not_the_same_community(
    index, sheet_fields, event
):
    assert not index.same_place(sheet(index, **sheet_fields), index.event_place(event))


def test_parenthetical_project_list_is_not_split_into_community_labels():
    # Damac 19914: "Emirates Garden 2 (Maple - Magnolia - Mulberry)" is one JVC project. Its
    # fragment "Mulberry" is also a Damac Hills 2 phase alias; it must not give the event Damac.
    index = PlaceIndex(BUILDINGS, *load_place_aliases())
    event = index.event_place(
        {
            "area_name": "Jumeirah Village Circle",
            "project_name": "Emirates Garden 2 (Maple - Magnolia - Mulberry)",
            "building_name": "Emirates Garden 2 - Mulberry 1",
        }
    )
    assert "damachills2" not in event.community_labels
    assert not index.same_place(sheet(index, master_project="DAMAC HILLS 2"), event)


def test_known_building_community_outranks_a_contradicting_dld_master():
    # Damac 18902: DLD files "Reem - Mira Oasis Community Phase 3" under master DAMAC HILLS 2, but
    # the hierarchy holds that building in Al Yelayiss 1, which is also the row's legal area.
    index = PlaceIndex(
        [
            *BUILDINGS,
            {
                "name_key": "reemmiraoasiscommunityphase3",
                "community_key": "alyelayiss1",
                "project_key": "",
            },
        ],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    event = index.event_place(
        {
            "master_project_en": "DAMAC HILLS 2",
            "area_name_en": "Al Yelayiss 1",
            "project_name_en": "REEM - MIRA OASIS COMMUNITY PHASE 3",
            "building_name_en": "Reem - Mira Oasis Community Phase 3",
        }
    )
    assert not index.same_place(sheet(index, master_project="DAMAC HILLS 2"), event)


def test_numbered_sub_communities_in_one_naming_system_must_agree(index):
    # Emirates Living 13163: DLD's master "Springs - 2" is not the sheet's "Springs - 1".
    place = sheet(index, master_project="Emirates Living", project_name="Springs - 1")
    row = {"project_name_en": "Emirates Living - Springs 12", "area_name_en": "Al Thanayah Fourth"}
    assert not index.same_place(
        place, index.event_place({**row, "master_project_en": "Springs - 2"})
    )
    assert index.same_place(place, index.event_place({**row, "master_project_en": "Springs - 1"}))


def test_dxbi_the_springs_number_is_a_different_numbering_and_is_not_compared(index):
    place = sheet(index, master_project="Emirates Living", project_name="Springs - 1")
    dxbi = {
        "area_name": "Emirates Living",
        "project_name": "The Springs 2",
        "building_name": "The Springs 2",
    }
    assert index.same_place(place, index.event_place(dxbi))


def test_a_shared_tower_number_needs_close_name_stems(index):
    # Furjan OLD 24293: "Glamz Residence Tower 2" is not "Starz Tower 2".
    place = sheet(index, master_project="Al Furjan", building_name="Glamz Residence Tower 2")
    furjan = {"area_name": "Al Furjan"}
    assert not index.same_place(
        place, index.event_place({**furjan, "building_name": "Starz Tower 2"})
    )
    assert index.same_place(
        place, index.event_place({**furjan, "building_name": "Glamz Residences Tower 2"})
    )


def test_a_bare_tower_number_still_agrees_with_any_stem(index):
    place = sheet(index, master_project="Al Furjan", building_name="Tower 2")
    furjan = {"area_name": "Al Furjan"}
    assert index.same_place(place, index.event_place({**furjan, "building_name": "Starz Tower 2"}))


def test_an_initialism_after_a_community_name_is_the_same_community(index):
    # JVT Until August 309: "Jumeirah Village Triangle (JVT)" is Jumeirah Village Triangle.
    place = sheet(index, area_name="Jumeirah Village Triangle (JVT)")
    assert index.same_place(place, index.event_place({"area_name": "Jumeirah Village Triangle"}))
    assert not index.same_place(place, index.event_place({"area_name": "Jumeirah Village Circle"}))


def test_a_comma_names_the_community_after_the_project(index):
    # City Walk Old 1937: DXBI files Fern under "Central Park, City Walk".
    place = sheet(index, master_project="City Walk", project_name="Fern", building_name="Fern")
    event = index.event_place(
        {
            "area_name": "Central Park",
            "project_name": "Central Park, City Walk",
            "building_name": "Fern",
        }
    )
    assert "citywalk" in event.community_labels
    assert index.same_place(place, event)


def test_a_project_named_like_the_sheet_community_survives_the_hierarchy_override():
    # Victory Heights old 155: the hierarchy holds the project in Dubai Sports City, but the row
    # itself calls its project "Victory Heights", which is what the sheet calls its community.
    index = PlaceIndex(
        [{"name_key": "victoryheights", "community_key": "dubaisportscity", "project_key": ""}],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    event = index.event_place(
        {
            "area_name": "Dubai Sports City",
            "project_name": "Victory Heights",
            "building_name": "Victory Heights",
        }
    )
    assert index.same_place(sheet(index, master_project="VICTORY HEIGHTS"), event)


@pytest.mark.parametrize(
    ("master", "project", "same"),
    [
        ("Springs - 5", "Emirates Living - Springs 4", True),
        ("Springs - 4", "Emirates Living - Springs 4", False),  # a different master number
        ("Emaar's Street Of Dreams", "Emirates Living - Springs 1", False),  # no number at all
    ],
)
def test_a_dld_springs_project_must_carry_the_sheets_springs_number(index, master, project, same):
    # Emirates Living Sheet1 2: sheet "Springs - 5"; DLD files the sale under the project
    # "Emirates Living - Springs 1" with the master "Emaar's Street Of Dreams".
    place = sheet(index, master_project="Emirates Living", project_name="Springs - 5")
    event = index.event_place(
        {
            "master_project_en": master,
            "project_name_en": project,
            "area_name_en": "Al Thanayah Fourth",
        }
    )
    assert index.same_place(place, event) is same


def test_a_project_or_building_named_after_a_community_does_not_outrank_the_dld_master(index):
    # Furjan OLD 10051: DLD files a Business Bay villa (area Burj Khalifa) under the project
    # "AL FURJAN" and the building "Al Furjan". Its master says where it is.
    place = sheet(index, master_project="Al Furjan", project_name="Al Furjan")
    row = {
        "area_name_en": "Burj Khalifa",
        "master_project_en": "Business Bay",
        "project_name_en": "AL FURJAN",
        "building_name_en": "Al Furjan",
    }
    assert not index.same_place(place, index.event_place(row))
    # Without a master the same labels still say Al Furjan (DXBI's legal-area filing).
    assert index.same_place(
        place, index.event_place({k: v for k, v in row.items() if k != "master_project_en"})
    )


def test_a_city_walk_master_survives_a_hierarchy_that_files_the_building_under_al_wasl():
    # City Walk Sheet1 925: DLD master "City Walk", building Thyme, which the hierarchy holds in the
    # legal area Al Wasl. "City Walk" is not a hierarchy community, so nothing contradicts it.
    index = PlaceIndex(
        [*BUILDINGS, {"name_key": "thyme", "community_key": "alwasl", "project_key": ""}],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    place = sheet(index, master_project="City Walk", project_name="Thyme", building_name="Thyme")
    row = {
        "area_name_en": "Al Wasl",
        "master_project_en": "City Walk",
        "project_name_en": "Thyme",
        "building_name_en": "Thyme",
    }
    assert index.same_place(place, index.event_place(row))
    # and a sheet that names only the community still finds the building
    assert index.same_place(sheet(index, master_project="City Walk"), index.event_place(row))


def test_a_project_under_a_dld_master_is_still_the_projects_own_community_label():
    # Victory Heights old 466: DLD master Dubai Sports City, project VICTORY HEIGHTS. The project
    # is not a hierarchy community, so it is no conflicting master and its label stays.
    index = PlaceIndex(
        [{"name_key": "victoryheights", "community_key": "dubaisportscity", "project_key": ""}],
        PROJECT_ALIASES,
        MASTER_ALIASES,
    )
    row = {
        "area_name_en": "Al Hebiah Fourth",
        "master_project_en": "Dubai Sports City",
        "project_name_en": "VICTORY HEIGHTS",
    }
    assert index.same_place(sheet(index, master_project="VICTORY HEIGHTS"), index.event_place(row))


def test_a_master_known_only_as_a_name_stays_the_master_when_the_row_names_a_building(index):
    # "City Walk" is a master the hierarchy only knows as a building/project name; a row that names
    # its own building ("Myrtle") keeps it, so DXBI's City Walk events still agree.
    row = sheet(
        index, master_project="Verve", project_name="Central Park", building_name="Verve Tower A"
    )
    assert "verve" in row.community_labels
    # ...and also when the building column held a unit code and was blanked
    assert "verve" in sheet(index, master_project="Verve", project_name="Verve").community_labels


def test_a_community_dash_building_label_names_both(index):
    row = sheet(index, master_project="ELO 2", building_name="DAMAC HILLS (2) - ELO 2")
    assert row.buildings == ("elo2",)
    assert "damachills2" in row.community_labels
    dxbi = index.event_place(
        {"area_name": "Damac Hills 2", "project_name": "Elo", "building_name": "Elo 2"}
    )
    assert index.same_place(row, dxbi)
    marina = index.event_place({"area_name": "Dubai Marina", "building_name": "Elo 2"})
    assert not index.same_place(row, marina)


def test_a_real_community_in_master_project_stays_the_community(index):
    row = sheet(index, master_project="DAMAC HILLS 2", building_name="NAVITAS E")
    assert "damachills2" in row.community_labels
    assert not index.same_place(
        row, index.event_place({"area_name": "Al Furjan", "building_name": "Navitas Tower E"})
    )


def test_a_bracketed_qualifier_does_not_hide_the_community(index):
    row = sheet(index, area_name="DAMAC Hills 2 (Akoya by DAMAC)", building_name="NAVITAS E")
    assert "damachills2" in row.community_labels


def test_the_community_in_a_building_label_counts_beside_the_area(index):
    # Monthly CRM exports: area "DAMAC Hills 2 (Akoya by DAMAC)", master "ELO 2",
    # building "DAMAC HILLS (2) - ELO 2"
    row = sheet(
        index,
        area_name="Some Area Label",
        master_project="ELO 2",
        building_name="DAMAC HILLS (2) - ELO 2",
    )
    assert {"damachills2", "somearealabel"} <= row.community_labels
    dxbi = index.event_place(
        {"area_name": "Damac Hills 2", "project_name": "Elo", "building_name": "Elo 2"}
    )
    assert index.same_place(row, dxbi)
