import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "admin"))

import admin_repository as ar  # noqa: E402
from admin_dummy_data import DummyBackend  # noqa: E402
from dashboard_stats import summarize  # noqa: E402


def test_summarize_dummy_data():
    repo = ar.AdminRepository(DummyBackend())
    x = summarize(repo.orders(), repo.members(), tables=30)
    assert not x["empty"]
    assert x["revenue"] == sum(x["by_hour"].values()) == sum(x["by_weekday"].values())
    assert x["avg_ticket"] == x["revenue"] // x["orders"]
    assert list(x["by_weekday"]) == ["월", "화", "수", "목", "금", "토", "일"]
    assert 0 <= x["returning_share"] <= 1


def test_summarize_empty():
    repo = ar.AdminRepository(DummyBackend())
    assert summarize(repo.orders().iloc[0:0], repo.members()) == {"empty": True}
