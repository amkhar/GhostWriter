#!/usr/bin/env python3
"""Demonstration of enhanced task classification explanations.

This script shows how the new TaskClassification model provides detailed
explanations for why tasks were not picked by GhostWriter.
"""
from models import NeglectedTask, TaskClassification, RunReport


def demo_enhanced_classification():
    """Create sample tasks with enhanced classification details."""
    
    # Task 1: Security-related (not auto-doable)
    auth_task = NeglectedTask(
        id="update-auth-system",
        title="Update authentication system",
        description="Migrate from basic auth to OAuth2 for better security",
        reason="Mentioned in 4 standups, still unassigned",
        auto_doable=False,
        classification=TaskClassification(
            auto_doable=False,
            reasoning="Security-sensitive authentication code requires careful manual review",
            decision_factors=[
                "Contains authentication keywords",
                "Security-critical system component", 
                "Requires multi-service coordination",
                "Risk of breaking user login flow"
            ],
            code_analysis="Found authentication logic in auth.py and middleware.py. OAuth2 integration would affect login flow, session management, and API endpoints.",
            risk_assessment="High risk of security vulnerabilities or service disruption if implemented incorrectly",
            suggested_approach="Create detailed security review process, implement in staging environment first, conduct penetration testing"
        )
    )
    
    # Task 2: Database migration (not auto-doable)  
    db_task = NeglectedTask(
        id="migrate-user-schema",
        title="Migrate user database schema",
        description="Add new columns for user preferences and deprecate old ones",
        reason="Discussed in 3 consecutive standups, blocked on planning",
        auto_doable=False,
        classification=TaskClassification(
            auto_doable=False,
            reasoning="Database migrations require careful planning and rollback strategies",
            decision_factors=[
                "Database schema modification",
                "Risk of data loss",
                "Requires downtime coordination",
                "Affects multiple services"
            ],
            code_analysis="Found user model in models/user.py and migration files in migrations/. Current schema has 50K+ user records.",
            risk_assessment="Risk of data corruption, service downtime, or breaking dependent services",
            suggested_approach="Create reversible migration script, test with production data copy, coordinate maintenance window"
        )
    )
    
    # Task 3: Simple typo fix (auto-doable)
    typo_task = NeglectedTask(
        id="fix-readme-typo",
        title="Fix typo in README",
        description="Correct spelling of 'installation' in setup instructions",
        reason="Mentioned in 2 standups as low priority",
        auto_doable=True,
        auto_doable_category="fix typo",
        classification=TaskClassification(
            auto_doable=True,
            category="fix typo",
            reasoning="Simple documentation fix with no risk",
            decision_factors=[
                "Documentation-only change",
                "Single file modification", 
                "No code logic affected",
                "Zero risk of breaking functionality"
            ],
            code_analysis="Found README.md file with typo on line 23 in installation section.",
            risk_assessment="No risk - documentation change only",
            suggested_approach="Direct text replacement - already safe for automation"
        )
    )
    
    # Task 4: Complex refactoring (not auto-doable)
    refactor_task = NeglectedTask(
        id="refactor-payment-logic",
        title="Refactor payment processing logic",
        description="Split large payment handler into smaller, testable functions",
        reason="Technical debt discussed in 5+ standups",
        auto_doable=False, 
        classification=TaskClassification(
            auto_doable=False,
            reasoning="Complex refactoring of business-critical payment code",
            decision_factors=[
                "Business-critical payment functionality",
                "Large-scale code restructuring required",
                "Affects billing and revenue systems",
                "Complex testing requirements"
            ],
            code_analysis="Found 500+ line payment_handler.py with complex business logic. Integrates with Stripe, PayPal, and internal billing systems.",
            risk_assessment="High financial risk if payment processing breaks. Could affect revenue collection.",
            suggested_approach="Break into smaller, incremental refactoring tasks. Add comprehensive tests first. Consider feature flags for gradual rollout."
        )
    )
    
    # Create a dry run report to show the enhanced explanations
    report = RunReport(
        run_id="demo-enhanced",
        dry_run=True,
        neglected_tasks=[auth_task, db_task, typo_task, refactor_task]
    )
    
    print("=== Enhanced GhostWriter Classification Demo ===\n")
    print("This shows how GhostWriter now explains why tasks were not picked:\n")
    
    # Print the enhanced markdown report
    print(report.to_markdown())


if __name__ == "__main__":
    demo_enhanced_classification()