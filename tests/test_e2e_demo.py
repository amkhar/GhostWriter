"""End-to-end demo test — full Box + Bedrock + agent flow, single task.

Uses sample/demo_single_task.txt (one transcript, one recurring task) so
Box AI Ask returns exactly one neglected task and the agent loop runs once.

Run:
    .venv/bin/pytest tests/test_e2e_demo.py -v -s
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env at import time so pytestmark can read env vars
load_dotenv(Path(__file__).parent.parent / ".env")
if os.environ.get("BEDROCK_API_KEY") and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_API_KEY"]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("BOX_TOKEN") and os.environ.get("BEDROCK_MODEL_ID")),
        reason="Requires BOX_TOKEN and BEDROCK_MODEL_ID in .env",
    ),
]

DEMO_TRANSCRIPT_DIR = Path(__file__).parent.parent / "sample"
SAMPLE_REPO = Path(__file__).parent.parent / "sample_repo"


@pytest.fixture()
def fresh_repo(tmp_path):
    """Copy sample_repo to a temp dir with a clean git state."""
    repo = tmp_path / "repo"
    shutil.copytree(str(SAMPLE_REPO), str(repo))
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@ghostwriter"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "GhostWriter Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
    return repo


def test_full_pipeline_single_task(fresh_repo, tmp_path):
    """
    Full e2e: Box upload → Box AI Extract → Box AI Ask → Bedrock classify
             → Strands orchestrator → worker → git diff → report.

    Uses demo_single_task.txt so only one neglected task is surfaced.
    Asserts the worker made a real code change in session.py.
    """
    from models import PipelineConfig
    from pipeline import run_pipeline

    # Use only the single-task demo transcript
    demo_dir = tmp_path / "transcripts"
    demo_dir.mkdir()
    shutil.copy(DEMO_TRANSCRIPT_DIR / "demo_single_task.txt", demo_dir)

    config = PipelineConfig(
        transcripts_dir=demo_dir,
        repo=fresh_repo,
        dry_run=False,
        box_dev_token=os.environ["BOX_TOKEN"],
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        bedrock_model_id=os.environ["BEDROCK_MODEL_ID"],
    )

    report = run_pipeline(config)

    print(f"\n{'='*60}")
    print(report.to_markdown())
    print('='*60)

    # At least one neglected task was found
    assert report.neglected_tasks, "Box AI should have found at least one neglected task"

    # At least one task was classified auto_doable and attempted
    assert report.worker_results, (
        "Expected at least one auto-attempted task. "
        f"Tasks found: {[t.title for t in report.neglected_tasks]}, "
        f"auto_doable: {[t.auto_doable for t in report.neglected_tasks]}"
    )

    result = report.worker_results[0]
    print(f"\n[worker] success={result.success}  test_status={result.test_status}")
    print(f"[worker] diff:\n{result.diff}")

    assert result.success, f"Worker failed: {result.error}"
    assert result.diff, "Expected a non-empty git diff"

    # The change should be in session.py
    assert "session" in result.diff.lower(), \
        f"Expected diff to touch session.py, got:\n{result.diff}"

    # Report was uploaded to Box
    assert report.report_box_file_id, "Report should have been uploaded to Box"
