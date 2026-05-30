"""Tests for pipeline.py — stage functions with mocked dependencies.

Properties tested:
  P3: Classification conservatism
  P4: Dry-run produces no working copy
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from hypothesis import given, settings, assume
from hypothesis import strategies as st
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import NeglectedTask, PipelineConfig, RunReport, WorkerResult
from pipeline import (
    build_report,
    classify,
    detect_recurrence,
    _UNSAFE_KEYWORDS,
    _AUTO_DOABLE_CATEGORIES,
)


# ------------------------------------------------------------------ #
# Unit tests — build_report
# ------------------------------------------------------------------ #

def test_build_report_dry_run():
    report = build_report(
        [NeglectedTask(id="t1", title="T1", description="D", reason="R", auto_doable=True)],
        [],
        dry_run=True,
        run_id="abc",
    )
    assert report.dry_run is True
    assert report.run_id == "abc"
    assert len(report.neglected_tasks) == 1
    assert report.worker_results == []


def test_build_report_full():
    report = build_report(
        [NeglectedTask(id="t1", title="T1", description="D", reason="R")],
        [WorkerResult(task_id="t1", success=True, summary="Done")],
        dry_run=False,
        run_id="xyz",
    )
    assert not report.dry_run
    assert len(report.worker_results) == 1


def test_build_report_empty():
    report = build_report([], [], dry_run=False, run_id="empty")
    assert report.neglected_tasks == []
    assert report.worker_results == []


# ------------------------------------------------------------------ #
# Unit tests — detect_recurrence
# ------------------------------------------------------------------ #

def test_detect_recurrence_parses_json():
    mock_box = MagicMock()
    mock_box.ai_ask_multi.return_value = json.dumps([
        {"title": "Fix README", "description": "Update run.sh to make run", "reason": "3 standups"},
        {"title": "Add null check", "description": "parse_user email", "reason": "2 standups"},
    ])
    result = detect_recurrence(["f1", "f2"], mock_box)
    assert len(result) == 2
    assert result[0].id == "fix-readme"
    assert result[1].id == "add-null-check"


def test_detect_recurrence_empty_file_ids():
    mock_box = MagicMock()
    result = detect_recurrence([], mock_box)
    assert result == []
    mock_box.ai_ask_multi.assert_not_called()


def test_detect_recurrence_raises_on_box_failure():
    mock_box = MagicMock()
    mock_box.ai_ask_multi.side_effect = Exception("Box API error")
    with pytest.raises(Exception, match="Box API error"):
        detect_recurrence(["f1"], mock_box)


# ------------------------------------------------------------------ #
# Unit tests — classify (mocked Bedrock)
# ------------------------------------------------------------------ #

def test_classify_unsafe_keyword_defaults_false():
    tasks = [
        NeglectedTask(id="t1", title="Update auth system", description="Refactor authentication", reason="R"),
    ]
    result = classify(tasks, "fake-model-id")
    assert result[0].auto_doable is False
    assert "unsafe keyword" in (result[0].classification_reasoning or "").lower()


def test_classify_calls_bedrock_for_safe_task():
    tasks = [
        NeglectedTask(id="t1", title="Fix typo in README", description="Fix a typo", reason="R"),
    ]
    mock_agent = MagicMock()
    mock_agent.return_value = '{"auto_doable": true, "category": "fix typo", "reasoning": "Safe fix"}'
    with patch("pipeline.Agent", return_value=mock_agent):
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = classify(tasks, "fake-model")
    assert result[0].auto_doable is True
    assert result[0].auto_doable_category == "fix typo"


def test_classify_defaults_false_on_bedrock_error():
    tasks = [
        NeglectedTask(id="t1", title="Add log line", description="Add logging", reason="R"),
    ]
    mock_agent = MagicMock()
    mock_agent.side_effect = Exception("Bedrock unavailable")
    with patch("pipeline.Agent", return_value=mock_agent):
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
            result = classify(tasks, "fake-model")
    assert result[0].auto_doable is False
    assert "failed" in (result[0].classification_reasoning or "").lower()


# ------------------------------------------------------------------ #
# Property-based tests
# ------------------------------------------------------------------ #

# Feature: ghostwriter, Property 3: Classification conservatism
@given(
    title=st.text(min_size=1, max_size=50),
    description=st.text(min_size=1, max_size=100),
    keyword=st.sampled_from(_UNSAFE_KEYWORDS),
)
@settings(max_examples=100, deadline=None)
def test_classify_unsafe_keywords_always_false(title, description, keyword):
    """Any task containing an unsafe keyword must be auto_doable=False."""
    # Inject keyword into title or description
    task = NeglectedTask(
        id="t1",
        title=title + " " + keyword,
        description=description,
        reason="R",
    )
    result = classify([task], "fake-model")
    assert result[0].auto_doable is False


# Feature: ghostwriter, Property 4: Dry-run produces no working copy
@given(st.booleans())
@settings(max_examples=50)
def test_dry_run_no_orchestrator_called(dry_run_flag):
    """When dry_run=True, orchestrate() is never called."""
    import agents.orchestrator as orch_module
    with patch.object(orch_module, "orchestrate", return_value=([], Path("/tmp"))) as mock_orch:
        with patch("pipeline.BoxClient") as mock_box_cls:
            mock_box = MagicMock()
            mock_box_cls.return_value = mock_box
            mock_box.ensure_folder.return_value = "folder1"
            mock_box.ai_ask_multi.return_value = "[]"
            mock_box.upload_report.return_value = "report1"

            config = PipelineConfig(
                transcripts_dir=None,
                paste_content="standup content",
                repo=Path("/tmp"),
                dry_run=dry_run_flag,
                box_dev_token="tok",
                aws_region="us-east-1",
                bedrock_model_id="model",
            )

            with patch("pipeline.ingest", return_value=[]):
                with patch("pipeline.extract", return_value=[]):
                    with patch("pipeline.detect_recurrence", return_value=[]):
                        from pipeline import run_pipeline
                        run_pipeline(config)

        if dry_run_flag:
            mock_orch.assert_not_called()
