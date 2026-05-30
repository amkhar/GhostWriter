"""Tests for main.py CLI — argument validation and env var checks."""
import os
import pytest
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app

runner = CliRunner()

_VALID_ENV = {
    "BOX_TOKEN": "tok",
    "AWS_REGION": "us-east-1",
    "BEDROCK_MODEL_ID": "anthropic.claude-3",
}


def test_missing_transcripts_and_paste_exits_1():
    with patch.dict(os.environ, _VALID_ENV):
        result = runner.invoke(app, ["run", "--repo", "/tmp"])
    assert result.exit_code != 0


def test_missing_repo_without_dry_run_exits_1(tmp_path):
    with patch.dict(os.environ, _VALID_ENV):
        result = runner.invoke(app, ["run", "--transcripts", str(tmp_path)])
    assert result.exit_code != 0


def test_dry_run_without_repo_is_ok(tmp_path):
    """--dry-run should not require --repo."""
    with patch.dict(os.environ, _VALID_ENV):
        with patch("pipeline.run_pipeline") as mock_pipe:
            mock_report = MagicMock()
            mock_report.to_markdown.return_value = "# Report"
            mock_report.report_box_file_id = "fid"
            mock_pipe.return_value = mock_report
            result = runner.invoke(app, ["run", "--transcripts", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0


def test_missing_box_token_exits_1(tmp_path):
    env = {k: v for k, v in _VALID_ENV.items() if k != "BOX_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        with patch("main.load_dotenv"):  # prevent .env file from loading
            result = runner.invoke(app, ["run", "--transcripts", str(tmp_path), "--dry-run"])
    assert result.exit_code != 0


def test_missing_aws_region_exits_1(tmp_path):
    env = {k: v for k, v in _VALID_ENV.items() if k != "AWS_REGION"}
    with patch.dict(os.environ, env, clear=True):
        with patch("main.load_dotenv"):
            result = runner.invoke(app, ["run", "--transcripts", str(tmp_path), "--dry-run"])
    assert result.exit_code != 0


def test_invalid_transcripts_dir_exits_1(tmp_path):
    with patch.dict(os.environ, _VALID_ENV):
        result = runner.invoke(app, ["run", "--transcripts", "/nonexistent/path", "--dry-run"])
    assert result.exit_code != 0


def test_invalid_repo_dir_exits_1(tmp_path):
    with patch.dict(os.environ, _VALID_ENV):
        result = runner.invoke(app, ["run", "--transcripts", str(tmp_path), "--repo", "/nonexistent"])
    assert result.exit_code != 0


def test_successful_run_prints_report(tmp_path):
    with patch.dict(os.environ, _VALID_ENV):
        with patch("pipeline.run_pipeline") as mock_pipe:
            mock_report = MagicMock()
            mock_report.to_markdown.return_value = "# GhostWriter Run Report\n\nAll good."
            mock_report.report_box_file_id = "box-file-123"
            mock_pipe.return_value = mock_report
            result = runner.invoke(app, ["run", "--transcripts", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0
    assert "GhostWriter Run Report" in result.output
