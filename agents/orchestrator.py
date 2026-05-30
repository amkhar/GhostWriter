"""Strands Orchestrator agent — coordinates worker agents using agents-as-tools pattern."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from strands import Agent, tool
from strands.models import BedrockModel

from agents.tools import read_file, list_dir, grep
from agents.worker import run_worker
from models import NeglectedTask, WorkerResult

logger = logging.getLogger("ghostwriter.orchestrator")

ORCHESTRATOR_SYSTEM_PROMPT = """You are GhostWriter Orchestrator, coordinating code-change workers.

For each auto-doable task you receive, call run_worker_agent with the task_id and task_description.
Use read_file, list_dir, and grep to understand the repository structure before delegating.
Collect all results and report what was done.
"""


def orchestrate(
    neglected: list[NeglectedTask],
    repo: Path,
    model_id: str,
    run_id: str,
) -> tuple[list[WorkerResult], Path]:
    """
    Set up working copy, run orchestrator agent over auto_doable tasks,
    commit changes, push branch. Returns (results, working_copy_path).
    """
    auto_tasks = [t for t in neglected if t.auto_doable]
    if not auto_tasks:
        logger.info("[GhostWriter][orchestrator] No auto-doable tasks — skipping")
        return [], repo

    # Create working copy
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"ghostwriter-{run_id}-"))
    working_copy = tmp_dir / "repo"
    logger.info("[GhostWriter][orchestrator] Copying repo to %s", working_copy)
    shutil.copytree(str(repo), str(working_copy))

    # Create feature branch
    branch = f"ghostwriter/auto-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
    logger.info("[GhostWriter][orchestrator] Creating branch %s", branch)
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(working_copy), check=True, capture_output=True)

    results: list[WorkerResult] = []

    # Build the worker tool with closure over working_copy and model_id
    @tool
    def run_worker_agent(task_id: str, task_description: str) -> str:
        """Invoke a worker agent to implement a single auto-doable task.

        Args:
            task_id: The unique identifier of the task (e.g. 'fix-typo-readme')
            task_description: Full description of what needs to be implemented

        Returns:
            A summary of what the worker did
        """
        logger.info("[GhostWriter][orchestrator] Delegating task %s to worker", task_id)
        result = run_worker(task_id, task_description, working_copy, model_id)
        results.append(result)

        if result.success:
            # Commit the changes
            _git_commit(working_copy, task_id, result.summary)

        return f"task_id={task_id} success={result.success} summary={result.summary}"

    # Build orchestrator agent
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    model = BedrockModel(model_id=model_id, region_name=aws_region)
    orchestrator = Agent(
        model=model,
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[run_worker_agent, read_file, list_dir, grep],
    )

    # Build task list prompt
    task_lines = []
    for t in auto_tasks:
        line = f"- task_id={t.id}: {t.title} — {t.description}"
        if t.user_guidance:
            line += f"\n  USER GUIDANCE: {t.user_guidance}"
        task_lines.append(line)
    prompt = (
        f"Repository is at: {working_copy}\n\n"
        f"Auto-doable tasks to implement:\n" + "\n".join(task_lines) + "\n\n"
        "For each task, call run_worker_agent. Report when all tasks are done."
    )

    logger.info("[GhostWriter][orchestrator] Starting orchestrator with %d tasks", len(auto_tasks))
    try:
        orchestrator(prompt)
    except Exception as e:
        logger.error("[GhostWriter][orchestrator] Orchestrator error: %s", e)

    # Push branch (best-effort)
    _git_push(working_copy, branch)

    return results, working_copy


def _git_commit(working_copy: Path, task_id: str, summary: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(working_copy), capture_output=True)
    msg = f"ghostwriter: [{task_id}] {summary}"
    subprocess.run(["git", "commit", "-m", msg], cwd=str(working_copy), capture_output=True)
    logger.info("[GhostWriter][orchestrator] Committed: %s", msg)


def _git_push(working_copy: Path, branch: str) -> None:
    r = subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=str(working_copy), capture_output=True, text=True,
    )
    if r.returncode == 0:
        logger.info("[GhostWriter][orchestrator] Pushed branch %s", branch)
    else:
        logger.warning("[GhostWriter][orchestrator] Push failed (no remote?): %s", r.stderr.strip())
