"""Strands Orchestrator — runs worker agents in parallel, each on its own copy/branch."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from agents.worker import run_worker
from models import NeglectedTask, WorkerResult

logger = logging.getLogger("ghostwriter.orchestrator")


def orchestrate(
    neglected: list[NeglectedTask],
    repo: Path,
    model_id: str,
    run_id: str,
) -> tuple[list[WorkerResult], Path]:
    """
    Run auto_doable tasks in parallel — each gets its own repo copy and branch.
    Returns (results, repo_path).
    """
    auto_tasks = [t for t in neglected if t.auto_doable]
    if not auto_tasks:
        logger.info("[GhostWriter][orchestrator] No auto-doable tasks — skipping")
        return [], repo

    logger.info("[GhostWriter][orchestrator] Starting %d tasks in parallel", len(auto_tasks))

    results: list[WorkerResult] = []

    with ThreadPoolExecutor(max_workers=min(len(auto_tasks), 4)) as pool:
        futures = {}
        for task in auto_tasks:
            future = pool.submit(_run_task_isolated, task, repo, model_id, run_id)
            futures[future] = task

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = "✅" if result.success else "❌"
                logger.info("[GhostWriter][orchestrator] %s %s: %s", status, task.id, result.summary)
            except Exception as e:
                logger.error("[GhostWriter][orchestrator] Task %s crashed: %s", task.id, e)
                results.append(WorkerResult(
                    task_id=task.id, success=False, summary="Orchestrator error", error=str(e)
                ))

    return results, repo


def _run_task_isolated(task: NeglectedTask, repo: Path, model_id: str, run_id: str) -> WorkerResult:
    """Run a single task on its own copy of the repo with its own branch."""
    # Create isolated working copy
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"gw-{run_id}-{task.id[:12]}-"))
    working_copy = tmp_dir / "repo"
    logger.info("[GhostWriter][orchestrator][%s] Copying repo to %s", task.id, working_copy)
    shutil.copytree(str(repo), str(working_copy))

    # Create unique branch for this task
    branch = f"ghostwriter/{task.id[:30]}-{datetime.utcnow().strftime('%H%M%S')}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(working_copy), check=True, capture_output=True)

    # Build task description with user guidance
    description = task.description
    if task.user_guidance:
        description += f"\n\nUSER GUIDANCE: {task.user_guidance}"

    # Run the worker
    result = run_worker(task.id, description, working_copy, model_id)

    if result.success and result.diff:
        _git_commit(working_copy, task.id, result.summary)
        _git_push(working_copy, branch)

    return result


def _git_commit(working_copy: Path, task_id: str, summary: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(working_copy), capture_output=True)
    # Truncate summary for commit message
    msg = f"ghostwriter: [{task_id}] {summary[:80]}"
    subprocess.run(["git", "commit", "-m", msg], cwd=str(working_copy), capture_output=True)
    logger.info("[GhostWriter][orchestrator] Committed: %s", msg)


def _git_push(working_copy: Path, branch: str) -> None:
    r = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=str(working_copy), capture_output=True, text=True,
    )
    if r.returncode == 0:
        logger.info("[GhostWriter][orchestrator] 🚀 Pushed branch %s", branch)
    else:
        logger.warning("[GhostWriter][orchestrator] Push failed (no remote?): %s", r.stderr.strip())
