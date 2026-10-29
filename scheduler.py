from datetime import datetime, timedelta

LADDER = [1, 3, 7, 14, 30, 60, 120]
RANK = {"low": 0, "normal": 1, "high": 2}
OUTCOMES = ["independent", "partial", "needed_help", "could_not_reproduce"]


def next_stage(stage, outcome, ladder=LADDER):
    if outcome == "independent":
        s = stage + 1
    elif outcome == "partial":
        s = max(stage, 0)
    elif outcome == "needed_help":
        s = stage - 1
    elif outcome == "could_not_reproduce":
        s = 0
    else:
        raise ValueError(f"unknown outcome: {outcome}")
    return min(max(s, 0), len(ladder) - 1)


def next_review(done_at, stage, ladder=LADDER):
    return done_at + timedelta(days=ladder[stage])


def is_due(p, now):
    return p["stage"] < 0 or datetime.fromisoformat(p["next_review_at"]) <= now


def build_queue(problems, budget_minutes, now):
    eligible = [p for p in problems if p["active"] and is_due(p, now)]
    due = sorted((p for p in eligible if p["stage"] >= 0),
                 key=lambda p: (-RANK[p["importance"]], p["next_review_at"]))
    new = sorted((p for p in eligible if p["stage"] < 0),
                 key=lambda p: (-RANK[p["importance"]], p["created_at"]))
    queue, used = [], 0
    for p in due + new:
        if not queue or used + p["estimated_minutes"] <= budget_minutes:
            queue.append(p)
            used += p["estimated_minutes"]
    return queue
