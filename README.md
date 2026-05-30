# 👻 GhostWriter

**Turn standups into shipped code.**

GhostWriter listens to your standup meetings, identifies the tasks your team keeps mentioning but never ships, and quietly implements the safe ones — then pushes a branch.

---

## How it works

```
🎙️ Record standup → 📝 Transcribe (Deepgram) → ☁️ Upload to Box
    → 🤖 Box AI finds neglected tasks → 🧠 LLM classifies safety
    → ⚙️ Agents implement in parallel → 🚀 Push branches to GitHub
```

1. **Record** — Speak your standup into the mic (or provide transcript files)
2. **Transcribe** — Deepgram Nova-3 transcribes in real-time with speaker diarization
3. **Ingest** — Transcripts upload to Box for AI processing
4. **Extract** — Box AI Extract pulls structured tasks from each transcript
5. **Recurrence** — Box AI Ask identifies tasks that keep coming up but never get done
6. **Classify** — Your chosen LLM (with codebase research) decides which are safe to auto-implement
7. **Implement** — Agents implement tasks in parallel, each on its own branch
8. **Push** — Each completed task gets its own branch pushed to GitHub

---

## Quick start

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Install optional provider dependencies (choose your provider)
pip install -e ".[gcp]"    # For Google Cloud Platform
pip install -e ".[all]"    # For all providers

# Configure
cp .env.example .env
# Configure your chosen LLM provider + Box + Deepgram API keys

# Check provider status
python main.py providers

# Run with voice recording
python main.py record --repo /path/to/your/repo --provider bedrock

# Run on existing transcripts
python main.py run --transcripts ./sample --repo /path/to/your/repo

# Dry run (classify only, no code changes)
python main.py run --transcripts ./sample --dry-run
```

---

## LLM Provider Support

GhostWriter supports multiple LLM providers for classification and code generation:

### AWS Bedrock (default)
```bash
# .env configuration
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_API_KEY=your_api_key  # OR use AWS credentials
```

### Google Cloud Platform (Vertex AI)
```bash
# Install dependencies
pip install -e ".[gcp]"

# .env configuration
LLM_PROVIDER=gcp
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1
GCP_MODEL_ID=claude-3-5-sonnet@20241022
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Microsoft Azure OpenAI
```bash
# .env configuration
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name
AZURE_MODEL_ID=gpt-4o
```

### Auto-detection
GhostWriter can automatically detect the best available provider:
```bash
python main.py providers  # Show current status
```

---

## Web UI

A full web interface for the GhostWriter workflow:

```bash
cd web && ./start.sh
# Open http://localhost:3000
```

Click the mic button → talk → stop → watch the pipeline run live with animated stage cards, agent thinking panels, and real-time diffs.

---

## Pluggable coding agents

Set `GHOSTWRITER_AGENT` to swap the implementation engine:

| Value | Engine | Best for |
|---|---|---|
| `strands` (default) | Strands SDK + your LLM provider | Simple tasks, configurable provider |
| `kiro` | kiro-cli | Complex tasks, loops, better tool use |
| `claude-code` | Anthropic claude CLI | Complex tasks, alternative model |

```bash
GHOSTWRITER_AGENT=kiro python main.py run --transcripts ./sample --repo .
```

When using `kiro` or `claude-code`, the agent also handles codebase research during classification — giving much better accuracy on what's actually safe to implement.

---

## Interactive overrides

When the classifier skips a task, GhostWriter prompts you:

```
💡 Override Skipped Tasks?
  Build a caching layer for API responses
  Reason skipped: Requires architectural decisions...
  Provide implementation details (or Enter to skip): Add a simple @lru_cache decorator to the fetch_user function in api.py
  ✅ Forced auto-doable with your guidance
```

Your guidance is passed directly to the worker agent AND stored in `.ghostwriter_feedback.jsonl` for future reinforcement learning.

---

## Parallel execution

When multiple tasks are classified as auto-doable:
- Each task gets its **own copy** of the repo
- Each runs on its **own branch** (`ghostwriter/<task-id>-<timestamp>`)
- Tasks execute **in parallel** (up to 4 concurrent workers)
- Auto-doable tasks start **immediately** — no waiting for user override prompts

---

## Authentication

### Box (CCG — recommended)
Client Credentials Grant tokens auto-refresh forever. Set in `.env`:
```
BOX_CLIENT_ID_A=your_client_id
BOX_SECRET_A=your_client_secret
BOX_ENTERPRISE_ID=your_enterprise_id
```

### Box (Developer token — quick testing)
Expires every 60 minutes. Set `BOX_TOKEN=...` in `.env`.

### LLM Provider Authentication
See the [provider configuration section](#llm-provider-support) above for your chosen provider.

### Deepgram (voice recording)
Free $200 credit at https://console.deepgram.com. Set `DEEPGRAM_API_KEY=...` in `.env`.

---

## Safety model

- **Codebase-aware classification** — classifier greps the repo before deciding, sees actual code scope
- **Unsafe keyword fast-path** — auth, payment, migration, delete → always blocked
- **Write path confinement** — agents can only write inside the working copy
- **Shell allowlist** — only test/lint commands allowed
- **Baseline test check** — only reverts if tests *regressed* (were passing, now broken)
- **Branch isolation** — every change goes to its own branch, never touches main

---

## Project structure

```
GhostWriter/
├── main.py              # CLI: run + record + providers commands
├── pipeline.py          # 7-stage pipeline with parallel execution
├── box_client.py        # Box API (CCG + dev token auth)
├── models.py            # Pydantic data models
├── voice.py             # Deepgram live mic transcription
├── ui.py                # Rich terminal UI (cards, spinners, panels)
├── feedback.py          # User override store (JSONL for RL)
├── providers/           # LLM provider abstraction
│   ├── __init__.py      # Provider factory and exports
│   ├── base.py          # Base provider interface
│   ├── bedrock.py       # AWS Bedrock implementation
│   ├── gcp.py           # Google Cloud Platform implementation
│   ├── azure.py         # Microsoft Azure implementation
│   └── factory.py       # Provider factory and auto-detection
├── agents/
│   ├── orchestrator.py  # Parallel task runner (ThreadPoolExecutor)
│   ├── worker.py        # Pluggable agent backends (strands/kiro/claude)
│   └── tools.py         # Sandboxed filesystem + shell tools
├── web/
│   ├── api/server.py    # FastAPI backend with SSE streaming
│   ├── frontend/        # Next.js + Tailwind UI
│   └── start.sh         # One-command launcher
├── tests/               # Unit + property-based tests (Hypothesis)
├── sample/              # Sample standup transcripts
├── sample_repo/         # Demo repo for testing
└── .github/workflows/   # CI (pytest on push/PR)
```

---

## Testing

```bash
pytest                              # Unit tests (63 tests)
pytest -m integration               # E2E with real Box/Bedrock
```

---

## License

[Apache 2.0](LICENSE)