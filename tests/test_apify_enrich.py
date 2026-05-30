"""Tests for apify_enrich — gated no-op, enrichment, compat check, and report rendering."""
import os
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import NeglectedTask, RunReport
import apify_enrich


def _task(title="Add null check", description="parse_user email"):
    return NeglectedTask(id="t1", title=title, description=description, reason="3 standups")


def test_enrich_is_noop_without_token():
    with patch.dict(os.environ, {}, clear=True):
        tasks = [_task()]
        with patch("apify_enrich._run_actor") as mock_actor:
            out = apify_enrich.enrich(tasks)
        mock_actor.assert_not_called()
        assert out[0].priority is None and out[0].evidence == []


def test_enrich_sets_priority_and_evidence():
    hits = [{"title": "crash on empty email #142"}, {"title": "TypeError parse_user #156"},
            {"title": "signup crash review"}]
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok"}):
        with patch("apify_enrich._search", return_value=hits):
            out = apify_enrich.enrich([_task()])
    assert out[0].priority == "high"
    assert len(out[0].evidence) == 3
    assert "crash on empty email #142" in out[0].evidence[0]


def test_enrich_normal_priority_below_threshold():
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok"}):
        with patch("apify_enrich._search", return_value=[{"title": "one issue"}]):
            out = apify_enrich.enrich([_task()])
    assert out[0].priority == "normal"


def test_compat_check_flags_dependency_upgrade():
    """A bump task gets a compat constraint appended and priority forced high."""
    def fake_search(query, limit=10):
        if "incompatible" in query:
            return [{"title": "kafka-streams 3.8 breaks with broker 2.x"}]
        return []
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok"}):
        with patch("apify_enrich._search", side_effect=fake_search):
            out = apify_enrich.enrich([_task(title="Upgrade kafka-streams to 3.8",
                                            description="bump kafka-streams to 3.8")])
    assert out[0].priority == "high"
    assert any("Public reports on kafka-streams" in e for e in out[0].evidence)
    assert "COMPAT CONSTRAINT" in out[0].description


def test_compat_check_returns_none_when_clean():
    with patch.dict(os.environ, {"APIFY_TOKEN": "tok"}):
        with patch("apify_enrich._search", return_value=[]):
            assert apify_enrich.compat_check("requests", "2.32.3") is None


def test_report_renders_priority_and_evidence():
    t = _task()
    t.priority = "high"
    t.evidence = ["GitHub #142: crash on blank email", "2 reviews cite signup crash"]
    md = RunReport(run_id="r", dry_run=True, neglected_tasks=[t]).to_markdown()
    assert "**Priority:** high" in md
    assert "Evidence (via Apify)" in md
    assert "GitHub #142: crash on blank email" in md
