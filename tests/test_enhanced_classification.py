"""Tests for enhanced classification features in models.py and pipeline.py.

Tests the new TaskClassification model and enhanced RunReport functionality.
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    NeglectedTask,
    TaskClassification,
    RunReport,
    WorkerResult,
)


def test_task_classification_model():
    """Test the new TaskClassification model."""
    classification = TaskClassification(
        auto_doable=False,
        reasoning="Contains authentication logic",
        decision_factors=["Security-sensitive operation", "Requires manual review"],
        code_analysis="Found auth tokens in config.py",
        risk_assessment="High security risk",
        suggested_approach="Manual security review required"
    )
    
    assert classification.auto_doable is False
    assert classification.reasoning == "Contains authentication logic"
    assert len(classification.decision_factors) == 2
    assert classification.code_analysis == "Found auth tokens in config.py"
    assert classification.risk_assessment == "High security risk"
    assert classification.suggested_approach == "Manual security review required"


def test_enhanced_dry_run_report_with_explanations():
    """Test that dry run report includes detailed explanations for skipped tasks."""
    
    # Task with enhanced classification
    task_with_classification = NeglectedTask(
        id="auth-task",
        title="Update auth system", 
        description="Fix authentication",
        reason="3 standups",
        auto_doable=False,
        classification=TaskClassification(
            auto_doable=False,
            reasoning="Security-sensitive authentication code",
            decision_factors=["Contains auth keywords", "High security risk"],
            risk_assessment="Could compromise user authentication",
            suggested_approach="Manual security review and testing required"
        )
    )
    
    # Task with basic classification
    task_basic = NeglectedTask(
        id="simple-task",
        title="Fix typo",
        description="Fix spelling",
        reason="2 standups",
        auto_doable=True,
        auto_doable_category="fix typo",
        classification_reasoning="Simple typo fix"
    )
    
    report = RunReport(
        run_id="test123",
        dry_run=True,
        neglected_tasks=[task_with_classification, task_basic]
    )
    
    md = report.to_markdown()
    
    # Check that it contains the new section
    assert "Tasks Not Auto-Doable (Why They Were Skipped)" in md
    assert "Why it was skipped:" in md
    assert "Security-sensitive authentication code" in md
    assert "Key factors:" in md
    assert "Contains auth keywords" in md
    assert "To make it auto-doable:" in md
    assert "Manual security review and testing required" in md


def test_full_run_report_with_detailed_explanations():
    """Test that full run report includes detailed explanations for report-only tasks."""
    
    skipped_task = NeglectedTask(
        id="complex-task",
        title="Database migration",
        description="Migrate user table",
        reason="4 standups",
        auto_doable=False,
        classification=TaskClassification(
            auto_doable=False,
            reasoning="Database migration requires careful planning",
            decision_factors=["Database operation", "Data loss risk", "Multi-service impact"],
            risk_assessment="Risk of data corruption or service downtime",
            suggested_approach="Create detailed migration plan, test in staging environment first"
        )
    )
    
    completed_task = NeglectedTask(
        id="typo-task",
        title="Fix README typo",
        description="Fix spelling error",
        reason="2 standups", 
        auto_doable=True,
        auto_doable_category="fix typo"
    )
    
    result = WorkerResult(
        task_id="typo-task",
        success=True,
        summary="Fixed spelling error in README"
    )
    
    report = RunReport(
        run_id="test456",
        dry_run=False,
        neglected_tasks=[skipped_task, completed_task],
        worker_results=[result]
    )
    
    md = report.to_markdown()
    
    # Check report-only section has detailed explanations
    assert "Report-Only Tasks (Not Auto-Implemented)" in md
    assert "Why not auto-doable:" in md
    assert "Database migration requires careful planning" in md
    assert "Decision factors:" in md
    assert "Database operation" in md
    assert "Data loss risk" in md
    assert "Risks identified:" in md
    assert "Risk of data corruption" in md
    assert "To make it auto-doable:" in md
    assert "Create detailed migration plan" in md


def test_backward_compatibility_with_classification_reasoning():
    """Test that tasks with only classification_reasoning (no full classification) still work."""
    
    legacy_task = NeglectedTask(
        id="legacy-task",
        title="Legacy task",
        description="Old-style task",
        reason="3 standups",
        auto_doable=False,
        classification_reasoning="Legacy classification system result"
    )
    
    report = RunReport(
        run_id="legacy123",
        dry_run=True,
        neglected_tasks=[legacy_task]
    )
    
    md = report.to_markdown()
    
    # Should still show basic reasoning in both places
    assert "**Why it was skipped:** Legacy classification system result" in md
    assert "**Reasoning:** Legacy classification system result" in md


if __name__ == "__main__":
    pytest.main([__file__, "-v"])