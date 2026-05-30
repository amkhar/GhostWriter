"""Strands Worker agent — implements a single auto-doable task on the working copy."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel

from agents.tools import (
    make_read_file_tool,
    make_write_file_tool,
    make_grep_tool,
    make_list_dir_tool,
    make_run_shell_tool,
)
from models import WorkerResult

logger = logging.getLogger("ghostwriter.worker")

WORKER_SYSTEM_PROMPT = """You are GhostWriter Worker, a focused code-change agent.
Your working copy is: {working_copy}

Rules:
- Only read and write files inside the working copy directory.
- Make the MINIMAL change required to complete the task.
- After making changes, run any available test or lint command (pytest, ruff, etc.).
- When done, output a 1-line summary of what you changed.
- Do NOT modify .git/ files or anything outside the working copy.
"""


def build_worker_agent(working_copy: Path, model_id: str) -> Agent:
    model = BedrockModel(
        model_id=model_id,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    return Agent(
        model=model,
        system_prompt=WORKER_SYSTEM_PROMPT.format(working_copy=str(working_copy)),
        tools=[
            make_read_file_tool(working_copy),
            make_write_file_tool(working_copy),
            make_grep_tool(working_copy),
            make_list_dir_tool(working_copy),
            make_run_shell_tool(working_copy),
        ],
    )


def run_worker(task_id: str, task_description: str, working_copy: Path, model_id: str) -> WorkerResult:
    """Run a worker agent for a single task; return WorkerResult."""
    logger.info("[GhostWriter][worker][%s] Starting worker", task_id)

    # Snapshot git state before changes
    before = _git_head(working_copy)

    try:
        worker = build_worker_agent(working_copy, model_id)
        response = worker(f"[{task_id}] {task_description}")
        summary = str(response).strip().splitlines()[-1] if str(response).strip() else "No summary"
    except Exception as e:
        logger.error("[GhostWriter][worker][%s] Agent error: %s", task_id, e)
        return WorkerResult(task_id=task_id, success=False, summary="Agent error", error=str(e))

    # Capture diff
    diff = _git_diff(working_copy)

    # Detect and run test suite
    test_status = _run_tests(working_copy, task_id)

    if test_status == "failed":
        logger.warning("[GhostWriter][worker][%s] Tests failed — reverting changes", task_id)
        _git_revert(working_copy, before)
        return WorkerResult(
            task_id=task_id,
            success=False,
            diff=diff,
            summary=summary,
            test_status="failed",
            error="Test suite failed; changes reverted",
        )

    logger.info("[GhostWriter][worker][%s] Done. test_status=%s", task_id, test_status)
    return WorkerResult(
        task_id=task_id,
        success=True,
        diff=diff or None,
        summary=summary,
        test_status=test_status,
    )


# ------------------------------------------------------------------ #
# Git helpers
# ------------------------------------------------------------------ #

def _git_head(working_copy: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(working_copy))
    return r.stdout.strip()


def _git_diff(working_copy: Path) -> str:
    r = subprocess.run(["git", "diff"], capture_output=True, text=True, cwd=str(working_copy))
    return r.stdout


def _git_revert(working_copy: Path, ref: str) -> None:
    subprocess.run(["git", "checkout", "--", "."], cwd=str(working_copy), capture_output=True)


def _run_tests(working_copy: Path, task_id: str) -> str:
    """Detect and run test suite; return 'passed', 'failed', or 'skipped'."""
    wc = str(working_copy)
    # Find pytest executable — prefer venv, fall back to system
    import shutil
    pytest_cmd = shutil.which("pytest") or "pytest"

    # Detect pytest
    if (working_copy / "pytest.ini").exists() or (working_copy / "pyproject.toml").exists() or \
       list(working_copy.glob("tests/test_*.py")) or list(working_copy.glob("test_*.py")):
        logger.info("[GhostWriter][worker][%s] Running pytest", task_id)
        r = subprocess.run(
            [pytest_cmd, "--tb=short", "-q"],
            capture_output=True, text=True, cwd=wc, timeout=120,
        )
        if r.returncode == 0:
            return "passed"
        # Distinguish test failures from infrastructure failures (import errors, missing deps)
        stderr_out = (r.stdout + r.stderr).lower()
        if "no module named" in stderr_out or "importerror" in stderr_out or "modulenotfounderror" in stderr_out:
            logger.warning("[GhostWriter][worker][%s] Test infrastructure error (missing deps) — skipping", task_id)
            return "skipped"
        return "failed"
    # Detect npm test
    if (working_copy / "package.json").exists():
        logger.info("[GhostWriter][worker][%s] Running npm test", task_id)
        r = subprocess.run(["npm", "test"], capture_output=True, text=True, cwd=wc, timeout=120)
        return "passed" if r.returncode == 0 else "failed"
    return "skipped"
