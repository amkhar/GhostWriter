<div align="center">

# 👻 GhostWriter

**AI-powered neglected-task auto-implementer**

GhostWriter watches your standup transcripts, finds the tasks your team keeps mentioning but never ships, and quietly implements the safe ones — then opens a PR.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Powered by Box AI](https://img.shields.io/badge/Box-AI-0061D5?logo=box&logoColor=white)](https://developer.box.com/guides/box-ai/)
[![Powered by AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-FF9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com/bedrock/)

</div>

---

## How it works

GhostWriter runs a 7-stage pipeline:

```
CLI (main.py)
  └─ Pipeline (pipeline.py)
       ├─ Stage 1 · Ingest      Upload transcripts to Box
       ├─ Stage 2 · Extract     Box AI extracts tasks per transcript
       ├─ Stage 3 · Recurrence  Box AI identifies tasks mentioned across multiple meetings
       ├─ Stage 4 · Classify    Bedrock LLM decides which tasks are safe to auto-implement
       ├─ Stage 5 · Orchestrate Strands Orchestrator agent coordinates workers
       ├─ Stage 6 · Implement   Strands Worker agents make the actual code changes
       └─ Stage 7 · Report      Markdown run report → stdout + Box upload
```

`--dry-run` stops after Stage 4 — no code is ever touched.

---

## Prerequisites

- Python 3.11+
- A [Box developer token](https://developer.box.com/guides/authentication/tokens/developer-tokens/) (or CCG credentials for production)
- AWS credentials with access to Amazon Bedrock (Claude 3.5 Sonnet recommended)

---

## Installation

```bash
# Recommended: uv
pip install uv
uv venv && source .venv/bin/activate
uv pip install -e .

# Or: plain pip
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Configuration

```bash
cp .env.example .env
# Fill in your credentials
```

| Variable | Required | Description |
|---|---|---|
| `BOX_TOKEN` | ✅ | Box developer token |
| `AWS_REGION` | ✅ | AWS region (e.g. `us-east-1`) |
| `BEDROCK_MODEL_ID` | ✅ | Bedrock model ID (e.g. `us.anthropic.claude-3-5-sonnet-20241022-v2:0`) |
| `BOX_ROOT_FOLDER_ID` | ☑️ | Box folder to use as root (default: `"0"` = root) |

AWS credentials are resolved from the standard chain: IAM role → `~/.aws/credentials` → environment variables.

---

## Usage

### Full run — find and implement neglected tasks

```bash
ghostwriter run \
  --transcripts ./sample \
  --repo ./sample_repo
```

### Dry run — classify only, no code changes

```bash
ghostwriter run \
  --transcripts ./sample \
  --dry-run
```

### Pipe a transcript from stdin

```bash
cat my_standup.txt | ghostwriter run --paste --dry-run
```

---

## Try the demo

The `sample/` directory has 3 standup transcripts that reference the same 3 recurring tasks. The `sample_repo/` directory has the corresponding code with those issues present.

| Task | What GhostWriter does |
|---|---|
| Update README — replace `run.sh` with `make run` | Edits `README.md` |
| Add null check on `parse_user` email field | Edits `user.py` |
| Add session expiry log line in `session.py` | Edits `session.py` |

```bash
# See what would be done
ghostwriter run --transcripts ./sample --dry-run

# Actually do it
ghostwriter run --transcripts ./sample --repo ./sample_repo
```

GhostWriter creates a `ghostwriter/auto-<timestamp>` branch, commits each change separately, and uploads a Markdown run report to Box.

---

## Safety model

GhostWriter is conservative by design.

- **Allowlist-only auto-implementation** — only tasks that match safe categories (fix typo, update docs, add null check, add log line, bump dependency, add unit test, rename for consistency) are ever attempted.
- **Unsafe keyword fast-path** — tasks mentioning `auth`, `payment`, `database migration`, `delete`, `drop table`, etc. are immediately marked non-auto-doable.
- **Write path confinement** — worker agents can only read/write files inside the working copy. Any path traversal attempt raises a `SecurityError`.
- **Shell allowlist** — agents can only run a fixed set of commands (`pytest`, `ruff`, `eslint`, `make test`, etc.).
- **Test-gated commits** — if the test suite fails after a change, the change is reverted before committing.
- **Branch isolation** — all changes go to a new `ghostwriter/auto-*` branch. `main`/`master` is never touched.

---

## Testing

Tests are split into **unit** tests (fast, fully mocked — no credentials or network) and **integration** tests (real Box + Bedrock + git + agent flow). Integration tests are marked `integration` and deselected by default.

```bash
# Unit tests only (default)
pytest

# Integration tests (requires BOX_TOKEN + BEDROCK_MODEL_ID in .env, plus sample_repo/)
pytest -m integration -v -s
```

The unit suite includes both example-based and property-based tests (via [Hypothesis](https://hypothesis.readthedocs.io/)):

| Property | What it verifies |
|---|---|
| P1 · Write path confinement | Worker can never write outside the working copy (100 examples) |
| P2 · Shell allowlist | Non-allowlisted commands are always rejected (200 examples) |
| P3 · Classification conservatism | Tasks with unsafe keywords are never marked auto-doable |
| P4 · Dry-run isolation | Dry run never produces a working copy |
| P5 · Task extraction schema | Box AI responses always produce valid Task objects (200 examples) |
| P7 · Report completeness | Run reports always include all neglected tasks |

---

## Project structure

```
ghostwriter/
├── main.py              # CLI entry point (Typer)
├── pipeline.py          # 7-stage pipeline
├── box_client.py        # Box API layer (upload, AI Extract, AI Ask)
├── models.py            # Pydantic data models
├── agents/
│   ├── orchestrator.py  # Strands Orchestrator agent
│   ├── worker.py        # Strands Worker agent
│   └── tools.py         # Sandboxed filesystem + shell tools
├── tests/
│   ├── test_tools.py    # P1, P2 property tests
│   ├── test_models.py   # P7 property tests
│   ├── test_box_client.py  # P5 property tests
│   ├── test_pipeline.py # P3, P4 property tests
│   └── test_cli.py      # CLI unit tests
├── sample/              # 3 sample standup transcripts
├── sample_repo/         # Sample repo for the demo
├── .env.example         # Environment variable template
└── pyproject.toml       # Package config + dependencies
```

---

## Production: upgrading Box authentication

Developer tokens expire after 60 minutes. For production, switch to [Client Credentials Grant (CCG)](https://developer.box.com/guides/authentication/client-credentials/):

1. Create a CCG app in the Box Developer Console and note your `client_id` and `client_secret`.
2. Add to `.env`:
   ```
   BOX_CLIENT_ID=your_client_id
   BOX_CLIENT_SECRET=your_client_secret
   ```
3. In `box_client.py`, replace the `requests.Session` auth header:
   ```python
   from boxsdk import CCGAuth, Client
   auth = CCGAuth(client_id=..., client_secret=..., enterprise_id=...)
   client = Client(auth)
   ```

---

## License

[Apache 2.0](LICENSE)
