# Enhanced Task Classification Feature

## Summary

Added comprehensive explanation capabilities to GhostWriter to show users why tasks were not picked or deemed not auto-doable, providing clear feedback about the classification reasoning and decision process.

## Changes Made

### 1. Enhanced Data Models (`models.py`)
- **New `TaskClassification` model** with detailed fields:
  - `auto_doable`: Boolean decision
  - `category`: Classification category if auto-doable
  - `reasoning`: Clear 1-2 sentence explanation
  - `decision_factors`: List of specific factors that influenced the decision
  - `code_analysis`: Summary of code research performed
  - `risk_assessment`: What risks were identified  
  - `suggested_approach`: How user could make it auto-doable

- **Enhanced `NeglectedTask` model**:
  - Added optional `classification` field for detailed classification info
  - Maintained backward compatibility with existing `classification_reasoning` field

- **Enhanced `RunReport.to_markdown()`**:
  - Added detailed explanations in dry-run reports showing why tasks were skipped
  - Enhanced report-only tasks section with comprehensive decision details
  - Maintained all existing functionality

### 2. Enhanced Classification Pipeline (`pipeline.py`)
- **Updated `classify()` function** to create detailed `TaskClassification` objects
- **Enhanced LLM prompt** to request structured decision factors, code analysis, risk assessment, and suggestions
- **Improved unsafe keyword detection** with detailed reasoning
- **Enhanced agent-based classification** for external agents (kiro/claude-code)
- **Updated user override system** to work with enhanced classification

### 3. Enhanced User Interface (`ui.py`)
- **Enhanced `show_classification()`** to display key decision factors for skipped tasks
- **New `show_classification_details()`** for detailed task classification display
- **New `show_skipped_tasks_summary()`** to group and summarize why tasks were skipped
- **Clean, informative output** that helps users understand decisions

### 4. Comprehensive Testing (`tests/test_enhanced_classification.py`)
- **4 new test cases** covering all enhanced functionality:
  - TaskClassification model validation
  - Dry-run reports with detailed explanations
  - Full-run reports with enhanced feedback
  - Backward compatibility with legacy classification

## User Benefits

### Before Enhancement
```
❌ auth-task → skip
❌ db-migration → skip  
✅ typo-fix → AUTO-DOABLE (fix typo)
```

### After Enhancement  
```
❌ auth-task → skip
    Reason: Security-sensitive authentication code requires manual review
    Key factors: Contains auth keywords, High security risk

❌ db-migration → skip
    Reason: Database migrations require careful planning and rollback strategies
    Key factors: Database schema modification, Risk of data loss

✅ typo-fix → AUTO-DOABLE (fix typo)
```

### Detailed Reports Now Include:
- **Why tasks were skipped** with specific reasoning
- **Decision factors** that influenced the classification  
- **Code analysis** showing what was found in the codebase
- **Risk assessment** explaining potential dangers
- **Suggested approaches** for making tasks auto-doable

## Example Enhanced Report Section

```markdown
## Tasks Not Auto-Doable (Why They Were Skipped)

### `update-auth-system`: Update authentication system
**Why it was skipped:** Security-sensitive authentication code requires careful manual review
**Key factors:**
- Contains authentication keywords
- Security-critical system component  
- Requires multi-service coordination
- Risk of breaking user login flow
**To make it auto-doable:** Create detailed security review process, implement in staging environment first, conduct penetration testing
```

## Backward Compatibility

✅ All existing functionality preserved  
✅ Legacy `classification_reasoning` field still supported  
✅ Existing tests continue to pass  
✅ No breaking changes to API or CLI  

## Code Quality

✅ All linting checks pass (`ruff check`)  
✅ All 67 existing tests continue to pass  
✅ 4 new comprehensive tests added  
✅ Clean, well-documented code with proper error handling  

This enhancement significantly improves user experience by providing clear, actionable feedback about why GhostWriter made specific classification decisions, helping users understand the system's reasoning and how to potentially modify tasks to make them auto-doable.