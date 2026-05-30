"""Filesystem and shell tools for GhostWriter agents.

Tools are created as Strands-compatible tool objects using the @tool decorator.
Factory functions create tool instances bound to a specific working_copy path.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from strands import tool

logger = logging.getLogger("ghostwriter.tools")

SHELL_ALLOWLIST = [
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "flake8",
    "ruff",
    "ruff check",
    "eslint",
    "make test",
    "make lint",
    "npm test",
    "npm run test",
    "cargo test",
    "go test",
]


class SecurityError(Exception):
    pass


def _assert_inside_working_copy(path: Path, working_copy: Path) -> None:
    resolved = path.resolve()
    wc_resolved = working_copy.resolve()
    if not str(resolved).startswith(str(wc_resolved)):
        raise SecurityError(f"Path {resolved} is outside working copy {wc_resolved}")


def make_read_file_tool(working_copy: Path):
    """Create a read_file tool bound to working_copy."""
    @tool
    def read_file(path: str) -> str:
        """Read a file from the working copy.

        Args:
            path: File path (absolute or relative to working copy)

        Returns:
            File contents as string, or error message
        """
        p = Path(path)
        if not p.is_absolute():
            p = working_copy / p
        logger.info("[tool:read_file] %s", p)
        try:
            _assert_inside_working_copy(p, working_copy)
            return p.read_text(errors="replace")
        except SecurityError as e:
            logger.error("[tool:read_file] SECURITY VIOLATION: %s", e)
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {e}"

    return read_file


def make_write_file_tool(working_copy: Path):
    """Create a write_file tool bound to working_copy."""
    @tool
    def write_file(path: str, content: str) -> str:
        """Write content to a file inside the working copy.

        Args:
            path: File path (absolute or relative to working copy)
            content: Content to write

        Returns:
            'OK' on success, or error message
        """
        p = Path(path)
        if not p.is_absolute():
            p = working_copy / p
        logger.info("[tool:write_file] %s", p)
        try:
            _assert_inside_working_copy(p, working_copy)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return "OK"
        except SecurityError as e:
            logger.error("[tool:write_file] SECURITY VIOLATION: %s", e)
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {e}"

    return write_file


def make_grep_tool(working_copy: Path):
    """Create a grep tool bound to working_copy."""
    @tool
    def grep(pattern: str, path: str = ".") -> str:
        """Search for a pattern in files under the working copy.

        Args:
            pattern: Regex pattern to search for
            path: Directory or file to search (relative to working copy)

        Returns:
            Matching lines with file:line format
        """
        p = Path(path)
        if not p.is_absolute():
            p = working_copy / p
        logger.info("[tool:grep] pattern=%r in %s", pattern, p)
        try:
            result = subprocess.run(
                ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts",
                 "--include=*.md", "--include=*.txt", pattern, str(p)],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout or "(no matches)"
        except Exception as e:
            return f"ERROR: {e}"

    return grep


def make_list_dir_tool(working_copy: Path):
    """Create a list_dir tool bound to working_copy."""
    @tool
    def list_dir(path: str = ".") -> str:
        """List directory contents inside the working copy.

        Args:
            path: Directory path (relative to working copy)

        Returns:
            Newline-separated list of entries
        """
        p = Path(path)
        if not p.is_absolute():
            p = working_copy / p
        logger.info("[tool:list_dir] %s", p)
        try:
            _assert_inside_working_copy(p, working_copy)
            entries = [str(e.relative_to(working_copy)) for e in sorted(p.iterdir())]
            return "\n".join(entries)
        except SecurityError as e:
            logger.error("[tool:list_dir] SECURITY VIOLATION: %s", e)
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {e}"

    return list_dir


def make_run_shell_tool(working_copy: Path):
    """Create a run_shell tool bound to working_copy."""
    @tool
    def run_shell(command: str) -> str:
        """Run an allowlisted shell command in the working copy directory.

        Args:
            command: Shell command to run (must start with an allowlisted prefix)

        Returns:
            Combined stdout/stderr output, or error message
        """
        logger.info("[tool:run_shell] %s", command)
        allowed = any(command.strip().startswith(prefix) for prefix in SHELL_ALLOWLIST)
        if not allowed:
            msg = f"SECURITY VIOLATION: command not allowlisted: {command!r}"
            logger.error("[tool:run_shell] %s", msg)
            return f"ERROR: {msg}"
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=str(working_copy), timeout=120,
            )
            output = result.stdout
            if result.stderr:
                output += "\nSTDERR: " + result.stderr
            if result.returncode != 0:
                output += f"\nEXIT CODE: {result.returncode}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "ERROR: Command timed out after 120s"
        except Exception as e:
            return f"ERROR: {e}"

    return run_shell


# ------------------------------------------------------------------ #
# Standalone tools for orchestrator (read-only, no working copy bound)
# ------------------------------------------------------------------ #

@tool
def read_file(path: str) -> str:
    """Read any file (orchestrator use only).

    Args:
        path: Absolute file path to read

    Returns:
        File contents as string
    """
    try:
        return Path(path).read_text(errors="replace")
    except Exception as e:
        return f"ERROR: {e}"


@tool
def list_dir(path: str = ".") -> str:
    """List directory contents (orchestrator use only).

    Args:
        path: Directory path to list

    Returns:
        Newline-separated list of entries
    """
    try:
        entries = [str(e) for e in sorted(Path(path).iterdir())]
        return "\n".join(entries)
    except Exception as e:
        return f"ERROR: {e}"


@tool
def grep(pattern: str, path: str = ".") -> str:
    """Search for a pattern in files (orchestrator use only).

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search

    Returns:
        Matching lines
    """
    try:
        result = subprocess.run(
            ["grep", "-rn", pattern, path],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout or "(no matches)"
    except Exception as e:
        return f"ERROR: {e}"
