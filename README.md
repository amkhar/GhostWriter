# GhostWriter

GhostWriter is a local Python CLI tool that ingests standup/scrum meeting transcripts, uses Box AI to identify recurring neglected tasks, classifies which are safe to auto-implement using AWS Bedrock, and orchestrates multiple AI agents to implement those low-risk code changes on a working copy of your repository. It produces a Markdown run report and uploads it to Box.

## Architecture

```
CLI (main.py)
  └─ Pipeline (pipeline.py)
       ├─ Stage 1: Ingest — upload transcripts to Box
       ├─ Stage 2: Extract — Box AI Extract per transcript
       ├─ Stage 3: Recurrence — Box AI Ask multi-file
       ├─ Stage 4: Classify — Bedrock LLM via Strands
       ├─ Stage 5-6: Orchestrate — Strands Orchestrator + Worker agents
       └─ Stage 7: Report — Markdown to stdout + Box upload
```

Stages 1–4 run in `--dry-run` mode. Stages 5–6 are skipped in dry-run.

## Setup

### Prerequisites

- Python 3.11+
- AWS credentials with Bedrock access (Claude 3.5 Sonnet recommended)
- Box developer token (from Box Developer Console)

### Install

```bash
# Recommended: uv
pip install uv
uv venv && source .venv/bin/activate
uv pip install -e .

# Fallback: pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:

| Variable | Description |
|---|---|
| `BOX_TOKEN` | Box developer token |
| `AWS_REGION` | AWS region (e.g. `us-east-1`) |
| `BEDROCK_MODEL_ID` | Bedrock model ID (e.g. `us.anthropic.claude-3-5-sonnet-20241022-v2:0`) |

AWS credentials are loaded from the standard chain (`~/.aws/credentials`, IAM role, or env vars).

## Usage

### Full run

```bash
python main.py run \
  --transcripts ./sample \
  --repo ./sample_repo
```

### Dry run (stages 1–4 only, no code changes)

```bash
python main.py run \
  --transcripts ./sample \
  --dry-run
```

### Paste transcript from stdin

```bash
cat my_standup.txt | python main.py run --paste --dry-run
```

## Demo with sample data

The `sample/` directory contains 3 standup transcripts referencing the same 3 recurring tasks:

1. **Update README** — replace `run.sh` with `make run` (3 standups, unassigned)
2. **Add null check** — `parse_user` email field (3 standups, unassigned)
3. **Add session expiry log line** — missing `logger.info` in `session.py` (3 standups, unassigned)

The `sample_repo/` directory contains the corresponding code files with these issues present.

```bash
# Dry run to see what would be done
python main.py run --transcripts ./sample --dry-run

# Full run to auto-implement
python main.py run --transcripts ./sample --repo ./sample_repo
```

## Testing

```bash
pytest
```

Tests cover:
- **P1** Write path confinement (property-based, 100 examples)
- **P2** Shell allowlist enforcement (property-based, 200 examples)
- **P3** Classification conservatism for unsafe keywords (property-based)
- **P4** Dry-run produces no working copy
- **P5** Task extraction schema completeness (property-based, 200 examples)
- **P7** Report completeness (property-based, 100 examples)
- Unit tests for all pipeline stages, CLI validation, Box client

## Assumptions

1. **Box authentication**: Uses a developer token (`BOX_TOKEN`). Developer tokens expire after 60 minutes. For production, upgrade to Client Credentials Grant (CCG) — see the CCG upgrade path below.
2. **Bedrock model**: Any model supporting tool use works. Claude 3.5 Sonnet is recommended for best classification accuracy.
3. **Repository**: The `--repo` directory must be a git repository. GhostWriter creates a `ghostwriter/auto-<timestamp>` branch and never touches `main`/`master`.
4. **Working copy**: Created in `/tmp/ghostwriter-<run_id>/`. Cleaned up manually if needed.
5. **Box folder structure**: GhostWriter creates `transcripts/`, `tasks/`, and `reports/` folders under the root folder (default: Box root `"0"`).

## CCG Upgrade Path (Box Authentication)

For production use, replace the developer token with Client Credentials Grant:

1. In Box Developer Console, create a CCG app and note `client_id` and `client_secret`.
2. Add to `.env`:
   ```
   BOX_CLIENT_ID=your_client_id
   BOX_CLIENT_SECRET=your_client_secret
   ```
3. In `box_client.py`, replace the `requests.Session` auth header with:
   ```python
   from boxsdk import CCGAuth, Client
   auth = CCGAuth(client_id=..., client_secret=..., enterprise_id=...)
   client = Client(auth)
   ```

## Project Structure

```
GhostWriter/
├── main.py              # CLI entry point (typer)
├── pipeline.py          # Pipeline stage functions
├── box_client.py        # Box API layer
├── models.py            # Pydantic data models
├── agents/
│   ├── orchestrator.py  # Strands Orchestrator agent
│   ├── worker.py        # Strands Worker agent
│   └── tools.py         # Filesystem + shell tools
├── tests/
│   ├── test_tools.py    # P1, P2 property tests
│   ├── test_models.py   # P7 property tests
│   ├── test_box_client.py # P5 property tests
│   ├── test_pipeline.py # P3, P4 property tests
│   └── test_cli.py      # CLI unit tests
├── sample/              # 3 sample standup transcripts
├── sample_repo/         # Sample code repo for demo
├── .env.example         # Environment variable template
└── pyproject.toml       # Package config + dependencies
```
