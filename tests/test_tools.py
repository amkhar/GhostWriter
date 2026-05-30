"""Tests for agents/tools.py — path safety and shell allowlist.

Properties tested:
  P1: Worker write path confinement
  P2: Shell allowlist enforcement
"""
import pytest
from pathlib import Path
from hypothesis import given, settings, assume
from hypothesis import strategies as st

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agents.tools import (
    SecurityError,
    SHELL_ALLOWLIST,
    _assert_inside_working_copy,
    make_read_file_tool,
    make_write_file_tool,
    make_run_shell_tool,
    make_list_dir_tool,
)


# ------------------------------------------------------------------ #
# Unit tests — write path confinement (P1)
# ------------------------------------------------------------------ #

def test_write_inside_working_copy(tmp_path):
    write = make_write_file_tool(tmp_path)
    result = write(str(tmp_path / "hello.txt"), "hello")
    assert result == "OK"
    assert (tmp_path / "hello.txt").read_text() == "hello"


def test_write_outside_working_copy_rejected(tmp_path):
    write = make_write_file_tool(tmp_path)
    outside = str(tmp_path.parent / "evil.txt")
    result = write(outside, "evil")
    assert "ERROR" in result
    assert "outside working copy" in result.lower() or "security" in result.lower()


def test_write_path_traversal_rejected(tmp_path):
    write = make_write_file_tool(tmp_path)
    traversal = str(tmp_path / ".." / "evil.txt")
    result = write(traversal, "evil")
    assert "ERROR" in result


def test_assert_inside_working_copy_raises(tmp_path):
    outside = tmp_path.parent / "other"
    with pytest.raises(SecurityError):
        _assert_inside_working_copy(outside, tmp_path)


def test_assert_inside_working_copy_ok(tmp_path):
    inside = tmp_path / "subdir" / "file.txt"
    _assert_inside_working_copy(inside, tmp_path)  # should not raise


# ------------------------------------------------------------------ #
# Unit tests — shell allowlist (P2)
# ------------------------------------------------------------------ #

def test_run_shell_allowed_pytest(tmp_path):
    run = make_run_shell_tool(tmp_path)
    result = run("pytest --version")
    # Should attempt to run (may fail if pytest not installed, but not rejected)
    assert "SECURITY VIOLATION" not in result


def test_run_shell_rejected_rm(tmp_path):
    run = make_run_shell_tool(tmp_path)
    result = run("rm -rf /")
    assert "ERROR" in result
    assert "allowlist" in result.lower() or "security" in result.lower()


def test_run_shell_rejected_curl(tmp_path):
    run = make_run_shell_tool(tmp_path)
    result = run("curl http://evil.com")
    assert "ERROR" in result


def test_run_shell_rejected_empty(tmp_path):
    run = make_run_shell_tool(tmp_path)
    result = run("")
    assert "ERROR" in result


@pytest.mark.parametrize("cmd", SHELL_ALLOWLIST)
def test_run_shell_allowlist_prefixes_accepted(tmp_path, cmd):
    """Each allowlist prefix should not be rejected by the allowlist check."""
    run = make_run_shell_tool(tmp_path)
    result = run(cmd + " --help 2>/dev/null || true")
    # Should not be rejected by allowlist (may fail for other reasons)
    assert "SECURITY VIOLATION" not in result


# ------------------------------------------------------------------ #
# Property-based tests
# ------------------------------------------------------------------ #

# Feature: ghostwriter, Property 1: Write path confinement
@given(st.text(min_size=1))
@settings(max_examples=100)
def test_write_arbitrary_path_outside_wc_rejected(path_str):
    """Any path that resolves outside /tmp/ghostwriter-test should be rejected."""
    import tempfile
    wc = Path(tempfile.mkdtemp(prefix="gw-test-"))
    try:
        write = make_write_file_tool(wc)
        # Construct a path that is definitely outside
        outside = Path("/tmp") / ("evil_" + path_str[:20].replace("/", "_").replace("\x00", "_"))
        if str(outside.resolve()).startswith(str(wc.resolve())):
            return  # skip if accidentally inside
        result = write(str(outside), "x")
        assert "ERROR" in result
    finally:
        import shutil
        shutil.rmtree(str(wc), ignore_errors=True)


# Feature: ghostwriter, Property 2: Shell allowlist enforcement
@given(st.text(min_size=1, max_size=200))
@settings(max_examples=200)
def test_shell_allowlist_rejects_arbitrary_commands(cmd):
    """Any command not starting with an allowlist prefix should be rejected."""
    assume(not any(cmd.strip().startswith(prefix) for prefix in SHELL_ALLOWLIST))
    assume("\x00" not in cmd)  # skip null bytes
    import tempfile
    wc = Path(tempfile.mkdtemp(prefix="gw-test-"))
    try:
        run = make_run_shell_tool(wc)
        result = run(cmd)
        assert "ERROR" in result
    finally:
        import shutil
        shutil.rmtree(str(wc), ignore_errors=True)
