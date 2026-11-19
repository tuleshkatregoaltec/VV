from datetime import datetime, timezone

from app.crm.deal_models import DEAL_STAGES
from scripts.crm.seed_demo_deals import plan

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
MEMBERS = [("24a0ac0e-team", "agent-a"), ("b5e5722d-team", "agent-b")]


def test_every_agent_gets_deals_in_their_own_team():
    deals = plan(MEMBERS, per_agent=4, now=NOW)
    assert len(deals) == 8
    assert {(d.team_id, d.agent) for d in deals} == set(MEMBERS)


def test_events_replay_to_the_stored_stage_and_status():
    for d in plan(MEMBERS, per_agent=10, now=NOW):
        stages = DEAL_STAGES[d.deal_type]
        assert 0 <= d.stage_index < len(stages)
        kinds = [e[0] for e in d.events]
        assert kinds[0] == "created"
        assert kinds.count("stage") == d.stage_index
        times = [e[3] for e in d.events]
        assert times == sorted(times) and times[-1] <= NOW and times[0] == d.created_at
        if d.status == "open":
            assert "closed" not in kinds and d.closed_at is None and d.due_date
        else:
            assert d.events[-1][4]["outcome"] == d.status and d.closed_at == times[-1]
        if d.status == "won":
            assert d.stage_index == len(stages) - 1


def test_some_activity_falls_in_the_last_day():
    deals = plan(MEMBERS, per_agent=4, now=NOW)
    assert any((NOW - d.events[-1][3]).total_seconds() < 86_400 for d in deals)
