"""Apify-powered enrichment for neglected tasks.

Two use cases, both backed by Apify Store Actors:
  B. Public sentiment / known-issue mining  -> sets NeglectedTask.priority + evidence
  A/C. Dependency-bump compatibility check  -> appends a compat constraint + raises priority

No-ops cleanly when APIFY_TOKEN is unset, so the pipeline runs without Apify.
"""
from __future__ import annotations

import logging
import os
import re

import requests

from models import NeglectedTask

logger = logging.getLogger("ghostwriter.apify")

_APIFY = "https://api.apify.com/v2"
# Apify Store actor used to mine public issues/sentiment (overridable via env).
_SEARCH_ACTOR = os.environ.get("APIFY_SEARCH_ACTOR", "apify~google-search-scraper")

# Best-effort detector for "bump/upgrade <pkg> to <version>" tasks.
_UPGRADE_RE = re.compile(r"(?:bump|upgrade|update)\s+([\w.\-/]+)\s+(?:to\s+)?v?(\d[\w.\-]*)", re.I)


def _enabled() -> bool:
    return bool(os.environ.get("APIFY_TOKEN"))


def _run_actor(actor_id: str, run_input: dict, limit: int = 10) -> list[dict]:
    """Run an Apify Actor synchronously and return its dataset items."""
    resp = requests.post(
        f"{_APIFY}/acts/{actor_id}/run-sync-get-dataset-items",
        params={"token": os.environ["APIFY_TOKEN"], "limit": limit},
        json=run_input,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _search(query: str, limit: int = 10) -> list[dict]:
    try:
        pages = _run_actor(
            _SEARCH_ACTOR, {"queries": query, "maxPagesPerQuery": 1, "resultsPerPage": limit}, limit=1
        )
    except Exception as e:  # network/actor errors must never break the pipeline
        logger.warning("[apify] search failed for %r: %s", query, e)
        return []
    # Google Search Scraper returns page-level items with results under organicResults.
    results: list[dict] = []
    for p in pages:
        results.extend(p.get("organicResults") or [])
    return (results or pages)[:limit]


def _titles(items: list[dict], n: int = 3) -> list[str]:
    out = []
    for it in items:
        t = it.get("title") or it.get("text") or it.get("url")
        if t:
            out.append(str(t)[:140])
    return out[:n]


def compat_check(package: str, target_version: str) -> str | None:
    """Return a 1-line compatibility warning if public sources flag issues, else None."""
    items = _search(f'"{package}" {target_version} incompatible OR regression OR broke OR breaking')
    titles = _titles(items, 2)
    if titles:
        return f"⚠️ Public reports on {package} {target_version}: " + "; ".join(titles)
    return None


def enrich(tasks: list[NeglectedTask]) -> list[NeglectedTask]:
    """Annotate tasks with public-evidence priority and dependency-compat notes.

    No-op (returns tasks unchanged) when APIFY_TOKEN is not set.
    """
    if not _enabled():
        logger.info("[apify] APIFY_TOKEN not set — skipping enrichment")
        return tasks

    for t in tasks:
        # Use case B: public sentiment / known issues -> priority + evidence
        hits = _search(f"{t.title} bug OR issue OR complaint")
        t.evidence = _titles(hits, 3)
        t.priority = "high" if len(hits) >= 3 else "normal"

        # Use case A/C: dependency-upgrade compatibility constraint
        m = _UPGRADE_RE.search(f"{t.title} {t.description}")
        if m:
            note = compat_check(m.group(1), m.group(2))
            if note:
                t.evidence.append(note)
                t.description += f"\n\nCOMPAT CONSTRAINT (verify before bumping): {note}"
                t.priority = "high"
        logger.info("[apify] enriched %s priority=%s evidence=%d", t.id, t.priority, len(t.evidence))

    return tasks


# ------------------------------------------------------------------ #
# Competitor / market-gap scan: which popular integrations are we missing?
# ------------------------------------------------------------------ #

_COMP_DOMAIN = os.environ.get("APIFY_COMPETITOR_DOMAIN", "AI coding agent")
# Agent backends GhostWriter already supports (see agents/worker.py GHOSTWRITER_AGENT).
_SUPPORTED = ["strands", "kiro", "claude-code"]
# Popular alternatives in the same domain to check the market for.
_CANDIDATES = [
    "claude", "cursor", "github copilot", "aider", "windsurf",
    "devin", "openai codex", "gemini cli", "amazon q developer", "cline",
]


def scan_competitors(domain: str | None = None, supported: list[str] | None = None,
                     limit: int = 10) -> list[str]:
    """Use one Apify search to see which popular same-domain integrations show up in the
    market but aren't supported yet. Returns human-review suggestions (never auto-implemented).

    No-op (returns []) without APIFY_TOKEN.
    """
    if not _enabled():
        return []
    domain = domain or _COMP_DOMAIN
    supported_lc = {s.lower() for s in (supported or _SUPPORTED)}
    items = _search(f"most popular {domain} tools 2026", limit)
    blob = " ".join((it.get("title", "") + " " + it.get("description", "")) for it in items).lower()

    recs = []
    for c in _CANDIDATES:
        if c.lower() in supported_lc:
            continue
        if c.lower() in blob:  # the market is talking about it, but we don't support it
            recs.append(f"Add support for **{c}** — appears in current '{domain}' results but isn't supported yet")
    logger.info("[apify] competitor scan: %d suggestion(s)", len(recs))
    return recs[:5]
