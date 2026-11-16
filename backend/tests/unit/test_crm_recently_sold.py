from datetime import date, datetime, timezone

from app.crm.import_models import CrmPropertyContactClaim
from app.crm.recently_sold import summarize_sold_owners


def _sold(
    owner: str,
    prop: str,
    sold_on: date,
    *,
    price: int | None = 2_400_000,
    building: str = "Marina Gate 1",
    unit: str = "1204",
    phone: str | None = "+971500000001",
    bought_on: date | None = None,
    bought_price: int | None = None,
) -> CrmPropertyContactClaim:
    now = datetime.now(timezone.utc)
    return CrmPropertyContactClaim(
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint=f"{owner}-{prop}",
        owner_key=owner,
        property_key=prop,
        contact_name=f"Owner {owner}",
        phone_primary=phone,
        area_name="Dubai Marina",
        building_name=building,
        unit_number=unit,
        property_type="Apartment",
        ownership_status="former_owner",
        confidence_score=99,
        match_reason="A later sale was recorded",
        later_sale_date=sold_on,
        latest_sale_price_aed=price,
        transaction_date=bought_on,
        transaction_price_aed=bought_price,
        created_at=now,
        updated_at=now,
    )


def test_one_owner_with_two_sales_is_one_item_newest_first():
    owners = summarize_sold_owners(
        [
            _sold("o1", "p1", date(2026, 9, 1), price=1_000_000, unit="801"),
            _sold("o1", "p2", date(2026, 10, 5)),
        ]
    )
    assert len(owners) == 1
    owner = owners[0]
    assert owner.last_sold_on == date(2026, 10, 5)
    assert [sale["property_key"] for sale in owner.sales] == ["p2", "p1"]
    assert owner.notes == (
        "Sold Marina Gate 1 unit 1204 on 05 Oct 2026 for AED 2,400,000. (+1 more recent sales)"
    )


def test_owners_are_ordered_by_most_recent_sale():
    owners = summarize_sold_owners(
        [
            _sold("older", "p1", date(2026, 8, 10)),
            _sold("newer", "p2", date(2026, 10, 1)),
        ]
    )
    # The client asked for former owners sorted by their most recent change in owner status.
    assert [owner.owner_key for owner in owners] == ["newer", "older"]


def test_sale_without_unit_or_price_reads_cleanly():
    owners = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 10, 5), price=None, building="Arjan Villas", unit="")]
    )
    assert owners[0].notes == "Sold Arjan Villas on 05 Oct 2026."


def test_the_same_unit_listed_twice_counts_once():
    owners = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 9, 1)), _sold("o1", "p1", date(2026, 10, 5))]
    )
    assert len(owners[0].sales) == 1 and owners[0].sales[0]["sold_on"] == "2026-10-05"


def _item(notes: str, sales: list[dict]):
    from app.crm.inbound_models import SOLD_OWNER_SOURCE, CrmInboundEnquiry

    now = datetime.now(timezone.utc)
    return CrmInboundEnquiry(
        organization_id="org",
        contact_id=1,
        created_by_user_id="system",
        record_kind="unqualified_contact",
        intent="unknown",
        status="new",
        source=SOLD_OWNER_SOURCE,
        source_lead_id="o1",
        enquiry_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        raw_notes=notes,
        observed_data={"recent_sales": sales, "recently_sold_notes": notes},
        created_at=now,
        updated_at=now,
    )


def test_a_new_sale_refreshes_the_inbox_item():
    from app.crm.recently_sold import refresh_sold_owner_item

    old = summarize_sold_owners([_sold("o1", "p1", date(2026, 9, 1), unit="801")])[0]
    item = _item(old.notes, old.sales)
    new = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 9, 1), unit="801"), _sold("o1", "p2", date(2026, 10, 5))]
    )[0]

    assert refresh_sold_owner_item(item, new, datetime.now(timezone.utc)) is True
    assert item.enquiry_date.date() == date(2026, 10, 5)
    assert len(item.observed_data["recent_sales"]) == 2
    assert item.raw_notes == new.notes


def test_refresh_keeps_what_an_agent_changed():
    from app.crm.recently_sold import refresh_sold_owner_item

    old = summarize_sold_owners([_sold("o1", "p1", date(2026, 9, 1))])[0]
    item = _item(old.notes, old.sales)
    item.intent, item.status, item.record_kind = "buy", "qualified", "opportunity"
    item.assigned_user_id, item.raw_notes = "agent-1", "Called: looking for a villa"
    new = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 9, 1)), _sold("o1", "p2", date(2026, 10, 5))]
    )[0]

    refresh_sold_owner_item(item, new, datetime.now(timezone.utc))
    assert (item.intent, item.status, item.record_kind) == ("buy", "qualified", "opportunity")
    assert item.assigned_user_id == "agent-1"
    assert item.raw_notes == "Called: looking for a villa"


def test_unchanged_sales_are_not_rewritten():
    from app.crm.recently_sold import refresh_sold_owner_item

    owner = summarize_sold_owners([_sold("o1", "p1", date(2026, 9, 1))])[0]
    item = _item(owner.notes, owner.sales)
    item.enquiry_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert refresh_sold_owner_item(item, owner, datetime.now(timezone.utc)) is False


def test_units_sold_the_same_day_keep_a_stable_order():
    same_day = date(2026, 10, 5)
    one = summarize_sold_owners([_sold("o1", "b", same_day), _sold("o1", "a", same_day)])[0]
    two = summarize_sold_owners([_sold("o1", "a", same_day), _sold("o1", "b", same_day)])[0]
    # A re-run must not see a "change" just because the database returned rows in another order.
    assert one.sales == two.sales and one.notes == two.notes


async def test_ownership_changes_run_the_sync_and_never_fail_the_import(monkeypatch):
    from app.crm import recently_sold

    calls: list[str] = []

    async def fake_sync(db, *, organization_id, **_):
        calls.append(organization_id)
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(recently_sold, "sync_recently_sold_inbox", fake_sync)
    # An import or re-match has already been saved; the Inbox sync failing must not undo it.
    await recently_sold.sync_after_ownership_change(object(), organization_id="org")
    assert calls == ["org"]


def test_the_same_sale_from_two_imports_resolves_the_same_way():
    day = date(2026, 10, 5)
    a = _sold("o1", "p1", day, unit="1204", price=2_400_000)
    b = _sold("o1", "p1", day, unit="1204A", price=2_450_000)
    b.confidence_score = 80
    # Two owner-file imports can carry the same resale; the better-evidenced claim wins either way.
    assert summarize_sold_owners([a, b])[0].sales == summarize_sold_owners([b, a])[0].sales


async def test_inbox_owner_check_uses_the_owner_key_not_a_name_search(monkeypatch):
    from app.crm import inbound, inbound_repository
    from app.crm.inbound_models import CrmInboundContact

    now = datetime.now(timezone.utc)
    seller = CrmInboundContact(
        id=1,
        organization_id="org",
        full_name="Owner o1",
        phone="+971500000001",
        created_at=now,
        updated_at=now,
    )
    enquirer = CrmInboundContact(
        id=2, organization_id="org", full_name="Walk In", created_at=now, updated_at=now
    )
    searched: dict[str, object] = {}

    async def find_identity_claims(db, emails, names, organization_id, phones):
        searched["names"] = set(names)
        return []

    async def list_claims_by_owner_keys(db, organization_id, owner_keys):
        searched["owner_keys"] = set(owner_keys)
        return [_sold("o1", "p1", date(2026, 10, 5))]

    async def assessed(db, organization_id, claims):
        assert organization_id == "org"
        return claims

    monkeypatch.setattr(inbound, "_assessed_inbound_claims", assessed)
    monkeypatch.setattr(inbound_repository, "find_identity_claims", find_identity_claims)
    monkeypatch.setattr(inbound_repository, "list_claims_by_owner_keys", list_claims_by_owner_keys)

    result = await inbound._bulk_ownership_enrichments(
        object(), organization_id="org", contacts=[seller, enquirer], owner_keys={1: "o1"}
    )
    # A seller from the owner file is looked up by its owner key (indexed, exact), and is left
    # out of the name search that scans every owner-file row.
    assert searched["owner_keys"] == {"o1"}
    assert searched["names"] == {"walk in"}
    assert result[1].matched and result[1].prior_property_count == 1


def test_inbox_window_applies_to_every_item_by_its_date():
    from app.crm.inbound import _within_window

    old_sale = _item("Sold …", [])
    old_sale.enquiry_date = datetime(2026, 8, 20, tzinfo=timezone.utc)
    new_sale = _item("Sold …", [])
    new_sale.enquiry_date = datetime(2026, 10, 9, tzinfo=timezone.utc)
    old_enquiry = _item("Bayut enquiry", [])
    old_enquiry.source, old_enquiry.enquiry_date = (
        "Bayut",
        datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    new_enquiry = _item("Bayut enquiry", [])
    new_enquiry.source, new_enquiry.enquiry_date = (
        "Bayut",
        datetime(2026, 10, 27, tzinfo=timezone.utc),
    )
    today = date(2026, 10, 28)
    items = (old_sale, new_sale, old_enquiry, new_enquiry)

    # One window for the whole Inbox: a seller's date is the sale, an enquiry's the day received.
    assert [x for x in items if _within_window(x, 30, today)] == [new_sale, new_enquiry]
    assert all(_within_window(x, 90, today) for x in items)
    assert all(_within_window(x, None, today) for x in items)


def test_sale_shows_what_the_owner_paid_and_the_gain():
    owner = summarize_sold_owners(
        [
            _sold(
                "o1",
                "p1",
                date(2026, 9, 30),
                price=1_085_000,
                building="Beverly Boulevard",
                unit="512",
                bought_on=date(2024, 10, 4),
                bought_price=650_000,
            )
        ]
    )[0]
    # The client wants the purchase next to the sale: how much cash the seller freed up.
    assert owner.sales[0]["bought_on"] == "2024-10-04"
    assert owner.sales[0]["bought_price_aed"] == 650_000
    assert owner.notes == (
        "Sold Beverly Boulevard unit 512 on 30 Sep 2026 for AED 1,085,000 "
        "(bought 04 Oct 2024 for AED 650,000, +67%)."
    )


def test_a_loss_and_a_missing_purchase_price_read_cleanly():
    loss = summarize_sold_owners(
        [
            _sold(
                "o1",
                "p1",
                date(2026, 10, 8),
                price=1_390_000,
                building="Arbor View",
                unit="610",
                bought_on=date(2024, 9, 26),
                bought_price=1_472_828,
            )
        ]
    )[0]
    assert loss.notes.endswith("(bought 26 Sep 2024 for AED 1,472,828, -6%).")
    no_price = summarize_sold_owners(
        [_sold("o2", "p2", date(2026, 10, 8), bought_on=date(2024, 9, 26))]
    )[0]
    assert no_price.notes.endswith("for AED 2,400,000 (bought 26 Sep 2024).")


def test_a_seller_row_is_not_shown_as_a_purchase():
    # When the owner's own file row is the sale (they are the seller), its date is the sale.
    owner = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 10, 8), bought_on=date(2026, 10, 8), bought_price=2_400_000)]
    )[0]
    assert "bought" not in owner.notes
    assert owner.sales[0]["bought_on"] is None and owner.sales[0]["bought_price_aed"] is None


def _seda(bought_price: int | None = 3_900_000):
    return _sold(
        "o1",
        "p1",
        date(2026, 10, 9),
        price=6_700_000,
        building="Al Hatimi",
        unit="310",
        bought_on=date(2023, 4, 24),
        bought_price=bought_price,
    )


def test_cash_in_hand_is_the_sale_less_the_mortgage_taken_at_purchase():
    owner = summarize_sold_owners([_seda()], mortgages={("p1", "2023-04-24"): 60.0})[0]
    sale = owner.sales[0]
    # 6.7m sale less a 60% loan on the 3.9m purchase (2.34m): about 4.36m in hand.
    assert sale["mortgage_ltv_pct"] == 60.0
    assert sale["est_cash_in_hand_aed"] == 4_360_000


def test_no_mortgage_on_record_or_an_impossible_ltv_means_unknown():
    unknown = summarize_sold_owners([_seda()])[0].sales[0]
    assert unknown["mortgage_ltv_pct"] is None and unknown["est_cash_in_hand_aed"] is None
    # DLD data has LTVs over 100%; they cannot be a mortgage share, so they are not used.
    odd = summarize_sold_owners([_seda()], mortgages={("p1", "2023-04-24"): 227.0})[0].sales[0]
    assert odd["mortgage_ltv_pct"] is None and odd["est_cash_in_hand_aed"] is None


def test_the_purchase_is_found_by_unit_date_and_price():
    from app.crm.recently_sold import match_purchase_ltv

    rows = [
        {
            "unit_key": "310",
            "transaction_date": date(2023, 4, 25),
            "sale_amount_aed": 3_910_000,
            "ltv_pct": 60,
        },
        {
            "unit_key": "310",
            "transaction_date": date(2023, 4, 24),
            "sale_amount_aed": 1_000_000,
            "ltv_pct": 80,
        },
    ]
    # Same unit, within 2 days and 2% of the price the owner paid; another unit 310 is ignored.
    assert match_purchase_ltv(rows, "310", date(2023, 4, 24), 3_900_000) == 60.0
    assert match_purchase_ltv(rows, "310", date(2023, 6, 1), 3_900_000) is None


def test_approving_turns_a_recent_seller_into_an_unbriefed_buyer_lead():
    from app.crm.recently_sold import approve_as_buyer

    owner = summarize_sold_owners([_seda()])[0]
    item = _item(owner.notes, owner.sales)
    item.id = 9
    activity = approve_as_buyer(item, user_id="agent-1", now=datetime.now(timezone.utc))

    # A possible buyer with no brief yet, so no matchmaking. Who works it is decided through
    # the shared assignment operation (see the PostgreSQL approval test), not here.
    assert (item.intent, item.record_kind, item.assigned_user_id) == ("buy", "opportunity", None)
    assert item.criteria == {}
    # The sale stays with the lead.
    assert item.raw_notes == owner.notes and item.observed_data["recent_sales"] == owner.sales
    assert activity.body == "Approved as a possible buyer from a recent sale"
    assert activity.activity_type == "status_changed" and activity.enquiry_id == 9


def test_only_a_recent_seller_waiting_in_the_inbox_can_be_approved():
    import pytest
    from fastapi import HTTPException

    from app.crm.recently_sold import approve_as_buyer

    enquiry = _item("Bayut enquiry", [])
    enquiry.source = "Bayut"
    approved = _item("Sold …", [])
    approved.intent = "buy"
    for item in (enquiry, approved):  # a normal enquiry; a second approval
        with pytest.raises(HTTPException) as refused:
            approve_as_buyer(item, user_id="agent-1", now=datetime.now(timezone.utc))
        assert refused.value.status_code == 409


def test_a_later_sync_keeps_the_approval():
    from app.crm.recently_sold import approve_as_buyer, refresh_sold_owner_item

    old = summarize_sold_owners([_sold("o1", "p1", date(2026, 9, 1))])[0]
    item = _item(old.notes, old.sales)
    approve_as_buyer(item, user_id="agent-1", now=datetime.now(timezone.utc))
    item.assigned_user_id = "agent-1"  # as approve_recent_seller assigns the approving agent
    new = summarize_sold_owners(
        [_sold("o1", "p1", date(2026, 9, 1)), _sold("o1", "p2", date(2026, 10, 5))]
    )[0]
    refresh_sold_owner_item(item, new, datetime.now(timezone.utc))
    assert (item.intent, item.record_kind, item.assigned_user_id) == (
        "buy",
        "opportunity",
        "agent-1",
    )


def test_leads_list_leaves_out_contacts_that_are_not_leads_yet():
    from app.crm.inbound import _is_lead
    from app.crm.inbound_models import VITEVUE_LEASE_SOURCE

    seller = _item("Sold …", [])  # recently sold owner, still in the Inbox
    buyer = _item("Bayut enquiry", [])
    buyer.source, buyer.intent = "Property Finder", "buy"
    lease = _item("", [])
    lease.source = VITEVUE_LEASE_SOURCE  # undecided seller or landlord, shown in Leads
    # Inbox-only contacts must not take the Leads page's places (it loads a page of 500).
    assert [_is_lead(x) for x in (seller, buyer, lease)] == [False, True, True]
