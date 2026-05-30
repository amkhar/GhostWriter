"""Tests for ui_service.run_dry_run — dry-run path with mocked Box/Bedrock."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PipelineConfig, NeglectedTask, WorkerResult
import ui_service


def _config():
    return PipelineConfig(
        paste_content="standup content",
        dry_run=True,
        box_dev_token="tok",
        aws_region="us-east-1",
        bedrock_model_id="model",
    )


def test_run_dry_run_reports_progress_and_returns_report():
    neglected = [NeglectedTask(id="t1", title="Fix README", description="d", reason="3 standups")]
    seen = []
    with patch("ui_service.BoxClient") as box_cls, \
         patch("ui_service.P.ingest", return_value=[]), \
         patch("ui_service.P.extract", return_value=[]), \
         patch("ui_service.P.detect_recurrence", return_value=neglected), \
         patch("ui_service.P.classify", return_value=neglected) as mock_classify, \
         patch("ui_service.P._upload_report") as mock_upload:
        box_cls.return_value = MagicMock()
        report = ui_service.run_dry_run(_config(), lambda s, status: seen.append((s, status)))

    assert report.dry_run is True
    assert report.neglected_tasks == neglected
    mock_classify.assert_called_once()
    mock_upload.assert_called_once()
    done = {s for s, status in seen if status == "done"}
    assert set(ui_service.DRY_RUN_STAGES).issubset(done)


def test_run_dry_run_skips_classify_when_no_neglected():
    seen = []
    with patch("ui_service.BoxClient") as box_cls, \
         patch("ui_service.P.ingest", return_value=[]), \
         patch("ui_service.P.extract", return_value=[]), \
         patch("ui_service.P.detect_recurrence", return_value=[]), \
         patch("ui_service.P.classify") as mock_classify, \
         patch("ui_service.P._upload_report"):
        box_cls.return_value = MagicMock()
        report = ui_service.run_dry_run(_config(), lambda s, status: seen.append((s, status)))

    mock_classify.assert_not_called()
    assert ("Classify", "skipped") in seen
    assert report.neglected_tasks == []


def _full_config():
    return PipelineConfig(
        paste_content="standup content",
        repo=Path("/tmp"),
        dry_run=False,
        box_dev_token="tok",
        aws_region="us-east-1",
        bedrock_model_id="model",
    )


def test_run_full_orchestrates_auto_doable_and_returns_results():
    neglected = [NeglectedTask(id="t1", title="T", description="d", reason="r", auto_doable=True)]
    wr = [WorkerResult(task_id="t1", success=True, summary="done", diff="--- a\n+++ b")]
    seen = []
    with patch("ui_service.BoxClient") as box_cls, \
         patch("ui_service.P.ingest", return_value=[]), \
         patch("ui_service.P.extract", return_value=[]), \
         patch("ui_service.P.detect_recurrence", return_value=neglected), \
         patch("ui_service.P.classify", return_value=neglected), \
         patch("ui_service.P._upload_report"), \
         patch("agents.orchestrator.orchestrate", return_value=(wr, Path("/tmp"))) as mock_orch:
        box_cls.return_value = MagicMock()
        report = ui_service.run_full(_full_config(), lambda s, status: seen.append((s, status)))

    mock_orch.assert_called_once()
    assert report.worker_results == wr
    assert report.dry_run is False
    assert ("Orchestrate", "done") in seen


def test_run_full_skips_orchestrate_when_none_auto_doable():
    neglected = [NeglectedTask(id="t1", title="T", description="d", reason="r", auto_doable=False)]
    seen = []
    with patch("ui_service.BoxClient") as box_cls, \
         patch("ui_service.P.ingest", return_value=[]), \
         patch("ui_service.P.extract", return_value=[]), \
         patch("ui_service.P.detect_recurrence", return_value=neglected), \
         patch("ui_service.P.classify", return_value=neglected), \
         patch("ui_service.P._upload_report"), \
         patch("agents.orchestrator.orchestrate") as mock_orch:
        box_cls.return_value = MagicMock()
        report = ui_service.run_full(_full_config(), lambda s, status: seen.append((s, status)))

    mock_orch.assert_not_called()
    assert ("Orchestrate", "skipped") in seen
    assert report.worker_results == []
