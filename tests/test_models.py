"""Tests for models.py — Pydantic validation and RunReport.to_markdown().

Properties tested:
  P7: Report completeness
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    Task,
    NeglectedTask,
    WorkerResult,
    RunReport,
    StatusMentioned,
    PipelineConfig,
)


# ------------------------------------------------------------------ #
# Unit tests
# ------------------------------------------------------------------ #

def test_task_defaults():
    t = Task(title="Fix typo", description="Fix it", source_transcript="t.txt")
    assert t.status_mentioned == StatusMentioned.UNCLEAR
    assert t.is_action_item is False
    assert t.owner is None


def test_neglected_task_slug():
    n = NeglectedTask(id="fix-typo", title="Fix typo", description="Fix it", reason="3 standups")
    assert n.auto_doable is False


def test_worker_result_failed():
    r = WorkerResult(task_id="t1", success=False, summary="Failed", error="oops")
    assert r.test_status is None


def test_run_report_dry_run_markdown():
    report = RunReport(
        run_id="abc123",
        dry_run=True,
        neglected_tasks=[
            NeglectedTask(id="fix-readme", title="Fix README", description="Update run.sh to make run",
                          reason="3 standups", auto_doable=True, auto_doable_category="update readme"),
            NeglectedTask(id="add-null-check", title="Add null check", description="parse_user email",
                          reason="3 standups", auto_doable=False),
        ],
    )
    md = report.to_markdown()
    assert "# GhostWriter Run Report" in md
    assert "Neglected Tasks Found" in md
    assert "Auto-Doable Shortlist" in md
    assert "fix-readme" in md
    assert "Auto-Attempted Tasks" not in md  # dry run


def test_run_report_full_markdown():
    report = RunReport(
        run_id="xyz",
        dry_run=False,
        neglected_tasks=[
            NeglectedTask(id="t1", title="Task 1", description="desc", reason="reason", auto_doable=True),
        ],
        worker_results=[
            WorkerResult(task_id="t1", success=True, summary="Done", diff="--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new"),
        ],
    )
    md = report.to_markdown()
    assert "Auto-Attempted Tasks" in md
    assert "Report-Only Tasks" in md
    assert "```diff" in md


def test_pipeline_config_validation():
    cfg = PipelineConfig(
        box_dev_token="tok",
        aws_region="us-east-1",
        bedrock_model_id="anthropic.claude-3",
    )
    assert cfg.dry_run is False
    assert cfg.box_root_folder_id == "0"


# ------------------------------------------------------------------ #
# Property-based tests
# ------------------------------------------------------------------ #

_neglected_strategy = st.builds(
    NeglectedTask,
    id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="-")),
    title=st.text(min_size=1, max_size=50),
    description=st.text(min_size=1, max_size=100),
    reason=st.text(min_size=1, max_size=100),
    auto_doable=st.booleans(),
    auto_doable_category=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    classification_reasoning=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
)

_worker_result_strategy = st.builds(
    WorkerResult,
    task_id=st.text(min_size=1, max_size=20),
    success=st.booleans(),
    diff=st.one_of(st.none(), st.text(min_size=0, max_size=200)),
    summary=st.text(min_size=1, max_size=100),
    test_status=st.one_of(st.none(), st.sampled_from(["passed", "failed", "skipped"])),
    error=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
)


# Feature: ghostwriter, Property 7: Report completeness
@given(
    neglected=st.lists(_neglected_strategy, min_size=0, max_size=5),
    results=st.lists(_worker_result_strategy, min_size=0, max_size=3),
    dry_run=st.booleans(),
)
@settings(max_examples=100)
def test_report_markdown_always_has_required_sections(neglected, results, dry_run):
    """RunReport.to_markdown() always contains the three required sections."""
    report = RunReport(run_id="test", dry_run=dry_run, neglected_tasks=neglected, worker_results=results)
    md = report.to_markdown()
    assert "# GhostWriter Run Report" in md
    assert "Neglected Tasks Found" in md
    if dry_run:
        assert "Auto-Doable Shortlist" in md
    else:
        assert "Auto-Attempted Tasks" in md
        assert "Report-Only Tasks" in md
