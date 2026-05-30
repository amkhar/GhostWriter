from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, field_validator


class StatusMentioned(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    UNCLEAR = "unclear"


class Task(BaseModel):
    title: str
    description: str
    owner: Optional[str] = None
    status_mentioned: StatusMentioned = StatusMentioned.UNCLEAR
    is_action_item: bool = False
    source_transcript: str  # filename


class NeglectedTask(BaseModel):
    id: str  # slug derived from title
    title: str
    description: str
    reason: str  # e.g. "raised in 3 standups, still unassigned"
    auto_doable: bool = False
    auto_doable_category: Optional[str] = None
    classification_reasoning: Optional[str] = None
    user_guidance: Optional[str] = None  # user-provided implementation details (skips classification)
    priority: Optional[str] = None  # "high" | "normal" — set by Apify public-evidence enrichment
    evidence: list[str] = []  # public-source findings (issues, reviews, compat notes) via Apify


class WorkerResult(BaseModel):
    task_id: str
    success: bool
    diff: Optional[str] = None
    summary: str
    test_status: Optional[str] = None  # "passed" | "failed" | "skipped"
    error: Optional[str] = None


class IngestedFile(BaseModel):
    filename: str
    box_file_id: str


class PipelineConfig(BaseModel):
    transcripts_dir: Optional[Path] = None
    paste_content: Optional[str] = None
    repo: Optional[Path] = None
    dry_run: bool = False
    box_dev_token: Optional[str] = None
    aws_region: str
    bedrock_model_id: str
    box_root_folder_id: str = "0"


class RunReport(BaseModel):
    run_id: str
    dry_run: bool
    neglected_tasks: list[NeglectedTask]
    worker_results: list[WorkerResult] = []
    report_box_file_id: Optional[str] = None

    def to_markdown(self) -> str:
        lines = [
            f"# GhostWriter Run Report",
            f"",
            f"**Run ID:** `{self.run_id}`  ",
            f"**Mode:** {'Dry Run' if self.dry_run else 'Full Run'}  ",
            f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"",
        ]

        # Neglected tasks section
        lines.append("## Neglected Tasks Found")
        if not self.neglected_tasks:
            lines.append("_No recurring neglected tasks detected._")
        else:
            for t in self.neglected_tasks:
                lines.append(f"### {t.title}")
                lines.append(f"- **ID:** `{t.id}`")
                lines.append(f"- **Description:** {t.description}")
                lines.append(f"- **Reason:** {t.reason}")
                if t.priority:
                    lines.append(f"- **Priority:** {t.priority}")
                if t.evidence:
                    lines.append("- **Evidence (via Apify):**")
                    for e in t.evidence:
                        lines.append(f"    - {e}")
                lines.append(f"- **Auto-doable:** {'✅ Yes' if t.auto_doable else '❌ No'}")
                if t.auto_doable_category:
                    lines.append(f"- **Category:** {t.auto_doable_category}")
                if t.classification_reasoning:
                    lines.append(f"- **Reasoning:** {t.classification_reasoning}")
                lines.append("")

        if self.dry_run:
            # Dry-run shortlist
            auto_doable = [t for t in self.neglected_tasks if t.auto_doable]
            lines.append("## Auto-Doable Shortlist (Dry Run)")
            if not auto_doable:
                lines.append("_No tasks classified as auto-doable._")
            else:
                for t in auto_doable:
                    lines.append(f"- `{t.id}`: {t.title} ({t.auto_doable_category})")
            return "\n".join(lines)

        # Auto-attempted tasks
        lines.append("## Auto-Attempted Tasks")
        attempted = [r for r in self.worker_results]
        if not attempted:
            lines.append("_No tasks were auto-attempted._")
        else:
            for r in attempted:
                status = "✅ Success" if r.success else "❌ Failed"
                lines.append(f"### `{r.task_id}` — {status}")
                lines.append(f"**Summary:** {r.summary}")
                if r.test_status:
                    lines.append(f"**Tests:** {r.test_status}")
                if r.diff:
                    lines.append("**Diff:**")
                    lines.append("```diff")
                    lines.append(r.diff)
                    lines.append("```")
                if r.error:
                    lines.append(f"**Error:** {r.error}")
                lines.append("")

        # Report-only tasks
        attempted_ids = {r.task_id for r in self.worker_results}
        report_only = [t for t in self.neglected_tasks if not t.auto_doable or t.id not in attempted_ids]
        lines.append("## Report-Only Tasks (Not Auto-Implemented)")
        if not report_only:
            lines.append("_All neglected tasks were auto-attempted._")
        else:
            for t in report_only:
                lines.append(f"- `{t.id}`: {t.title} — {t.reason}")

        return "\n".join(lines)
