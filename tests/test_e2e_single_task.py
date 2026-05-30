"""End-to-end demo test — single coding task, fast execution.

Bypasses Box upload/extract/recurrence (slow network) by injecting one
pre-canned NeglectedTask directly into classify → orchestrate → report.
Targets the session-expiry log-line task in sample_repo/session.py.

Run:
    .venv/bin/pytest tests/test_e2e_single_task.py -v -s
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SAMPLE_REPO = Path(__file__).parent.parent / "sample_repo"

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
# Translate BEDROCK_API_KEY → AWS_BEARER_TOKEN_BEDROCK at import time
if os.environ.get("BEDROCK_API_KEY") and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_API_KEY"]

# Skip if real credentials aren't present
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("BEDROCK_MODEL_ID"),
        reason="Requires BEDROCK_MODEL_ID env var (set in .env)",
    ),
]


@pytest.fixture()
def fresh_repo(tmp_path):
    """Copy sample_repo to a temp dir with a clean git state."""
    repo = tmp_path / "repo"
    shutil.copytree(str(SAMPLE_REPO), str(repo))
    subprocess.run(["git", "config", "user.email", "test@ghostwriter"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "GhostWriter Test"], cwd=str(repo), check=True)
    return repo


def test_single_task_session_log_line(fresh_repo):
    """
    E2E: classify one task → worker adds session-expiry log line → report shows diff.

    Verifies:
    - Bedrock classifies the task as auto_doable
    - Worker writes the log line into session.py
    - WorkerResult has success=True and a non-empty diff
    - Report markdown contains the diff
    """
    from models import NeglectedTask
    from pipeline import classify, build_report
    from agents.orchestrator import orchestrate

    model_id = os.environ["BEDROCK_MODEL_ID"]

    # --- Stage 4: Classify (single task) ---
    task = NeglectedTask(
        id="add-session-expiry-log-line",
        title="Add session expiry log line",
        description=(
            "In session.py, the get_session() function removes expired sessions "
            "but never logs it. Add logger.info(\"Session expired for user %s\", "
            "session[\"user_id\"]) where the TODO comment is."
        ),
        reason="Raised in 3 standups, still unassigned",
    )

    [task] = classify([task], model_id)
    print(f"\n[classify] auto_doable={task.auto_doable}  category={task.auto_doable_category}")
    assert task.auto_doable, f"Expected auto_doable=True, got reasoning: {task.classification_reasoning}"

    # --- Stage 5-6: Orchestrate (single task) ---
    results, working_copy = orchestrate([task], fresh_repo, model_id, run_id="e2e-test")

    assert len(results) == 1, f"Expected 1 WorkerResult, got {len(results)}"
    result = results[0]
    print(f"[worker] success={result.success}  test_status={result.test_status}")
    print(f"[worker] summary: {result.summary}")
    if result.diff:
        print(f"[worker] diff:\n{result.diff}")

    assert result.success, f"Worker failed: {result.error}"
    assert result.diff, "Expected a non-empty git diff"
    assert "session" in result.diff.lower() or "logger" in result.diff.lower(), \
        "Diff should touch session.py or add a logger call"

    # --- Stage 7: Report ---
    report = build_report([task], results, dry_run=False, run_id="e2e-test")
    md = report.to_markdown()
    print(f"\n--- Report ---\n{md}\n---")

    assert "Auto-Attempted Tasks" in md
    assert result.task_id in md
    assert "```diff" in md
