"""Tests for ui_service.run_dry_run — dry-run path with mocked Box/Bedrock."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PipelineConfig, NeglectedTask
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
