from datetime import date

from app.crm.rental_timing import available_from, lease_timing, parse_move_in, stale_caveat

TODAY = date(2026, 11, 3)


def test_iso_move_in():
    assert parse_move_in("2027-02-01", today=TODAY) == date(2027, 2, 1)


def test_day_month_year_move_in_is_read_day_first():
    # Dubai writes dates day first: 05/02/2027 is 5 Feb, not 2 May.
    assert parse_move_in("05/02/2027", today=TODAY) == date(2027, 2, 5)


def test_asap_is_today():
    assert parse_move_in("ASAP", today=TODAY) == TODAY
    assert parse_move_in("Immediately", today=TODAY) == TODAY


def test_month_without_year_is_next_occurrence():
    assert parse_move_in("January", today=TODAY) == date(2027, 1, 1)
    assert parse_move_in("December", today=TODAY) == date(2026, 12, 1)


def test_month_with_year():
    assert parse_move_in("March 2027", today=TODAY) == date(2027, 3, 1)


def test_unparseable_move_in_means_no_gate():
    # A tenant brief with no readable date must match as before, never crash.
    assert parse_move_in("flexible", today=TODAY) is None
    assert parse_move_in("Q1 2027", today=TODAY) is None
    assert parse_move_in(None, today=TODAY) is None
    assert parse_move_in("", today=TODAY) is None


def test_description_date_resolves_year_from_listing_date():
    text = "Spacious 2BR. Available from 15th Dec. 4 cheques."
    assert available_from(text, listed=date(2026, 10, 1)) == date(2026, 12, 15)


def test_description_date_with_year():
    text = "Available on 1st March 2027, chiller free"
    assert available_from(text, listed=date(2026, 10, 1)) == date(2027, 3, 1)


def test_description_available_in_month():
    assert available_from("Available in January", listed=date(2026, 10, 1)) == date(2027, 1, 1)


def test_description_available_now_is_listing_date():
    listed = date(2026, 6, 1)
    assert available_from("Vacant and ready to move in", listed=listed) == listed
    assert available_from("AVAILABLE NOW | high floor", listed=listed) == listed


def test_description_silent_returns_none():
    assert available_from("Sea view, gym, pool", listed=date(2026, 6, 1)) is None
    assert available_from(None, listed=date(2026, 6, 1)) is None


def test_lease_ending_after_move_in_is_disqualified():
    # Kian (27:38): a lease expiring after the tenant moves in leaves them homeless.
    assert lease_timing(date(2027, 3, 1), date(2027, 2, 1))[0] == "after"


def test_lease_ending_on_move_in_day_is_in_time():
    verdict, reason = lease_timing(date(2027, 2, 1), date(2027, 2, 1))
    assert verdict == "in_time"
    assert reason == "Lease ends 1 Feb 2027, before move-in 1 Feb 2027"


def test_unknown_lease_end_is_kept_for_review():
    assert lease_timing(None, date(2027, 2, 1)) == ("unknown", "Lease end unknown, verify")


def test_old_available_now_listing_gets_caveat():
    # Property Finder listings can be months old (19:54): their timing needs confirming.
    listed = date(2026, 7, 1)
    assert stale_caveat(125, listed, listed) == "Listed 125 days ago, confirm it's still available"
    assert stale_caveat(125, None, listed) == "Listed 125 days ago, confirm it's still available"
    assert stale_caveat(30, listed, listed) is None


def test_old_listing_with_future_date_needs_no_caveat():
    assert stale_caveat(125, date(2027, 1, 1), date(2026, 7, 1)) is None
