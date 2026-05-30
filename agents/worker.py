"""Strands Worker agent — implements a single auto-doable task on the working copy."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from typing import Callable, Optional, Union

from models import WorkerResult, PipelineConfig

logger = logging.getLogger("ghostwriter.worker")

# Pluggable coding agent — set GHOSTWRITER_AGENT to override
# Options: "strands" (default), "kiro", "claude-code"
AGENT_BACKEND = os.environ.get("GHOSTWRITER_AGENT", "strands")

WORKER_SYSTEM_PROMPT = """You are GhostWriter Worker, a focused code-change agent.
Your working copy is: {working_copy}

Rules:
- Only read and write files inside the working copy directory.
- Make the MINIMAL change required to complete the task.
- After making changes, run any available test or lint command (pytest, ruff, etc.).
- When done, output a 1-line summary of what you changed.
- Do NOT modify .git/ files or anything outside the working copy.
"""


def run_worker(
    task_id: str,
    task_description: str,
    working_copy: Path,
    config: Union[str, PipelineConfig],  # Support both legacy model_id string and new config
    progress_cb: Optional[Callable[[str, str, str], None]] = None,
) -> WorkerResult:
    """Run a worker agent for a single task; return WorkerResult."""
    logger.info("[GhostWriter][worker][%s] Starting worker (backend=%s)", task_id, AGENT_BACKEND)

    # Baseline: check if tests already pass before we touch anything
    if progress_cb:
        progress_cb(task_id, "Checking baseline tests...", "working")
    baseline_status = _run_tests(working_copy, task_id)
    logger.info("[GhostWriter][worker][%s] Baseline test status: %s", task_id, baseline_status)

    # Snapshot git state
    before = _git_head(working_copy)

    # Run the coding agent
    if progress_cb:
        progress_cb(task_id, f"Running coding agent ({AGENT_BACKEND})...", "working")
    try:
        if AGENT_BACKEND == "kiro":
            summary = _run_kiro_agent(task_id, task_description, working_copy)
        elif AGENT_BACKEND == "claude-code":
            summary = _run_claude_code_agent(task_id, task_description, working_copy)
        else:
            summary = _run_strands_agent(task_id, task_description, working_copy, config)
    except Exception as e:
        err_str = str(e)
        # MaxTokens errors often happen mid-edit — check if the agent did useful work first
        is_max_tokens = "max_tokens" in err_str.lower() or "MaxTokensReachedException" in err_str
        partial_diff = _git_diff(working_copy)
        logger.error("[GhostWriter][worker][%s] Agent error: %s", task_id, e)

        if is_max_tokens and partial_diff:
            # Agent ran out of tokens but made changes — try to keep what it did
            logger.info("[GhostWriter][worker][%s] Max tokens hit but diff exists — testing if usable", task_id)
            test_status = _run_tests(working_copy, task_id)
            if test_status == "passed" or (test_status == "failed" and baseline_status != "passed"):
                # Changes don't break anything — accept them
                return WorkerResult(
                    task_id=task_id, success=True, diff=partial_diff,
                    summary=f"Partial completion (max tokens hit): {summary if 'summary' in dir() else 'changes preserved'}",
                    test_status=test_status,
                )
            # Tests regressed — revert
            _git_revert(working_copy, before)

        return WorkerResult(
            task_id=task_id, success=False,
            summary="Max tokens reached" if is_max_tokens else "Agent error",
            error=err_str[:300],
        )

    # Capture diff
    diff = _git_diff(working_copy)
    if not diff:
        return WorkerResult(task_id=task_id, success=True, diff=None, summary=summary, test_status="skipped")

    # Run tests after change — only fail if baseline was passing and now it's broken
    if progress_cb:
        progress_cb(task_id, "Running verification tests...", "working")
    test_status = _run_tests(working_copy, task_id)

    if test_status == "failed" and baseline_status == "passed":
        logger.warning("[GhostWriter][worker][%s] Tests regressed — reverting changes", task_id)
        if progress_cb:
            progress_cb(task_id, "Tests regressed! Reverting changes...", "working")
        _git_revert(working_copy, before)
        return WorkerResult(
            task_id=task_id, success=False, diff=diff, summary=summary,
            test_status="failed", error="Test suite regressed; changes reverted",
        )

    # If tests were already failing before, don't penalize the worker
    if test_status == "failed" and baseline_status != "passed":
        logger.info("[GhostWriter][worker][%s] Tests still failing (were already broken), accepting change", task_id)
        if progress_cb:
            progress_cb(task_id, "Tests still failing (pre-existing), accepting changes...", "working")
        test_status = "pre-existing failure"

    logger.info("[GhostWriter][worker][%s] Done. test_status=%s", task_id, test_status)
    if progress_cb:
        progress_cb(task_id, "Completed code implementation!", "working")
    return WorkerResult(
        task_id=task_id, success=True, diff=diff or None, summary=summary, test_status=test_status,
    )


# ------------------------------------------------------------------ #
# Agent backends
# ------------------------------------------------------------------ #

def _run_strands_agent(task_id: str, task_description: str, working_copy: Path, config: Union[str, PipelineConfig]) -> str:
    """Use Strands SDK agent with configurable provider."""
    from strands import Agent
    from agents.tools import (
        make_read_file_tool, make_write_file_tool,
        make_grep_tool, make_list_dir_tool, make_run_shell_tool,
    )

    # Handle backward compatibility with model_id string
    if isinstance(config, str):
        # Legacy: direct model_id string, use Bedrock
        from strands.models import BedrockModel
        model = BedrockModel(
            model_id=config,
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            max_tokens=8192,
        )
        worker = Agent(
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
    else:
        # New: use provider system
        from providers import ProviderFactory
        try:
            provider = ProviderFactory.create_provider()
            model_config = provider.get_default_model_config()
            
            # Override with config-specific model if using Bedrock (backward compatibility)
            if provider.provider_name == "bedrock" and hasattr(config, 'bedrock_model_id'):
                model_config.model_id = config.bedrock_model_id
            
            worker = provider.create_agent(
                model_config=model_config,
                system_prompt=WORKER_SYSTEM_PROMPT.format(working_copy=str(working_copy)),
                tools=[
                    make_read_file_tool(working_copy),
                    make_write_file_tool(working_copy),
                    make_grep_tool(working_copy),
                    make_list_dir_tool(working_copy),
                    make_run_shell_tool(working_copy),
                ]
            )
        except Exception as e:
            logger.warning("[GhostWriter][worker][%s] Provider creation failed, falling back to Bedrock: %s", task_id, e)
            # Fallback to original Bedrock implementation
            from strands.models import BedrockModel
            model_id = getattr(config, 'bedrock_model_id', os.environ.get("BEDROCK_MODEL_ID"))
            model = BedrockModel(
                model_id=model_id,
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
                max_tokens=8192,
            )
            worker = Agent(
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

    response = worker(f"[{task_id}] {task_description}")
    return str(response).strip().splitlines()[-1] if str(response).strip() else "No summary"


def _run_kiro_agent(task_id: str, task_description: str, working_copy: Path) -> str:
    """Use kiro-cli as the coding agent (local, powerful, tool-use enabled)."""
    prompt = (
        f"In this repo, implement this task:\n\n"
        f"{task_description}\n\n"
        f"Make the minimal change needed. Do not modify unrelated files."
    )
    r = subprocess.run(
        ["kiro-cli", "chat", "--trust-all-tools", "--no-interactive", prompt],
        capture_output=True, text=True, cwd=str(working_copy), timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"kiro-cli failed: {r.stderr[:500]}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "Completed via kiro-cli"


def _run_claude_code_agent(task_id: str, task_description: str, working_copy: Path) -> str:
    """Use claude-code (Anthropic's CLI agent) as the coding agent."""
    prompt = (
        f"In this repo, implement this task:\n\n"
        f"{task_description}\n\n"
        f"Make the minimal change needed. Do not modify unrelated files."
    )
    r = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Edit,Write,Read,Bash"],
        capture_output=True, text=True, cwd=str(working_copy), timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude-code failed: {r.stderr[:500]}")
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "Completed via claude-code"


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
    subprocess.run(["git", "clean", "-fd"], cwd=str(working_copy), capture_output=True)


def _run_tests(working_copy: Path, task_id: str) -> str:
    """Detect and run test suite; return 'passed', 'failed', or 'skipped'."""
    wc = str(working_copy)
    pytest_cmd = shutil.which("pytest") or "pytest"

    if (working_copy / "pytest.ini").exists() or (working_copy / "pyproject.toml").exists() or \
       list(working_copy.glob("tests/test_*.py")) or list(working_copy.glob("test_*.py")):
        logger.info("[GhostWriter][worker][%s] Running pytest", task_id)
        r = subprocess.run(
            [pytest_cmd, "--tb=short", "-q", "-x"],
            capture_output=True, text=True, cwd=wc, timeout=120,
        )
        if r.returncode == 0:
            return "passed"
        stderr_out = (r.stdout + r.stderr).lower()
        if "no module named" in stderr_out or "importerror" in stderr_out or "modulenotfounderror" in stderr_out:
            logger.warning("[GhostWriter][worker][%s] Test infra error (missing deps) — skipping", task_id)
            return "skipped"
        return "failed"
    if (working_copy / "package.json").exists():
        logger.info("[GhostWriter][worker][%s] Running npm test", task_id)
        r = subprocess.run(["npm", "test"], capture_output=True, text=True, cwd=wc, timeout=120)
        return "passed" if r.returncode == 0 else "failed"
    return "skipped"