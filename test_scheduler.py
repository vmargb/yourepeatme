from datetime import datetime, timedelta

import scheduler as s

NOW = datetime(2026, 1, 10, 12)


def prob(i, stage=-1, imp="normal", mins=5, due_days=0):
    nxt = (NOW - timedelta(days=due_days)).isoformat() if stage >= 0 else None
    return dict(id=i, active=1, stage=stage, importance=imp, estimated_minutes=mins,
                next_review_at=nxt, created_at=f"2026-01-0{i}")


def test_stage_transitions():
    assert s.next_stage(-1, "independent") == 0
    assert s.next_stage(0, "independent") == 1
    assert s.next_stage(6, "independent") == 6
    assert s.next_stage(-1, "partial") == 0
    assert s.next_stage(3, "partial") == 3
    assert s.next_stage(-1, "needed_help") == 0
    assert s.next_stage(3, "needed_help") == 2
    assert s.next_stage(5, "could_not_reproduce") == 0


def test_interval():
    assert s.next_review(NOW, 0) == NOW + timedelta(days=1)
    assert s.next_review(NOW, 1) == NOW + timedelta(days=3)


def test_queue_priority_and_budget():
    ps = [prob(1), prob(2, 1, "low", due_days=5), prob(3, 1, "high", due_days=1),
          prob(4, 1, "high", due_days=3)]
    assert [p["id"] for p in s.build_queue(ps, 100, NOW)] == [4, 3, 2, 1]
    assert [p["id"] for p in s.build_queue(ps, 10, NOW)] == [4, 3]


def test_queue_always_one_and_skips_future():
    assert len(s.build_queue([prob(1, mins=60)], 5, NOW)) == 1
    future = prob(2, 1, due_days=-3)
    assert s.build_queue([future], 25, NOW) == []
