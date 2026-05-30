"""Feedback store — records user overrides for future reinforcement learning."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FEEDBACK_FILE = Path(__file__).parent / ".ghostwriter_feedback.jsonl"


def record_override(task_id: str, title: str, description: str, user_guidance: str, classification_reasoning: str | None = None):
    """Append a user override to the feedback store."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "task_id": task_id,
        "title": title,
        "description": description,
        "original_reasoning": classification_reasoning,
        "user_guidance": user_guidance,
        "action": "user_forced_auto_doable",
    }
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
