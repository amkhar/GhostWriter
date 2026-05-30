# Requirements Document

## Introduction

GhostWriter is a local Python CLI tool that ingests standup/scrum meeting transcripts, uses AI (via Box AI and AWS Bedrock) to identify recurring neglected tasks, classifies which are safe to auto-complete, and orchestrates multiple AI agents to implement those low-risk code changes on a working copy of the target repository. The tool produces a Markdown run report and uploads it to Box.

## Glossary

- **GhostWriter**: The CLI tool described in this document.
- **Transcript**: A standup or scrum meeting record in `.txt` or `.md` format.
- **Box**: The cloud storage and document AI platform used for file storage and AI extraction.
- **Box_Client**: The component responsible for all Box API interactions.
- **Pipeline**: The sequential processing component covering ingest, extract, recurrence, and classify steps.
- **Orchestrator**: The Strands orchestrator agent that coordinates worker agents.
- **Worker**: A Strands sub-agent that implements a single auto-doable task on the working copy.
- **Task**: A structured record extracted from a transcript with fields: title, description, owner, status_mentioned, is_action_item.
- **NeglectedTask**: A task identified as recurring across multiple transcripts but never resolved.
- **WorkerResult**: The output of a Worker agent: git diff, 1-line summary, and pass/fail status.
- **RunReport**: The aggregated Markdown report of the full pipeline run.
- **Working_Copy**: A temporary copy of the target repository where Workers make changes.
- **auto_doable**: A boolean flag on a NeglectedTask indicating it is safe for automated implementation.
- **Dry_Run**: A mode that executes steps 1–4 only, producing no code changes.
- **Allowlist**: The set of permitted shell commands Workers may execute.

---

## Requirements

### Requirement 1: CLI Entry Point

**User Story:** As a developer, I want a single CLI command to run the full GhostWriter pipeline, so that I can process transcripts and auto-complete neglected tasks without manual steps.

#### Acceptance Criteria

1. THE GhostWriter CLI SHALL accept a `run` subcommand with `--transcripts <dir>` and `--repo <dir>` arguments.
2. THE GhostWriter CLI SHALL accept a `--paste` argument as an alternative to `--transcripts` for providing transcript content via stdin.
3. THE GhostWriter CLI SHALL accept a `--dry-run` flag that restricts execution to steps 1–4 (ingest, extract, recurrence, classify) and produces no code changes.
4. WHEN `--dry-run` is specified, THE GhostWriter CLI SHALL print the neglected-task list with reasons and the auto_doable shortlist to stdout.
5. WHEN required arguments are missing or invalid, THE GhostWriter CLI SHALL print a descriptive error message and exit with a non-zero status code.
6. THE GhostWriter CLI SHALL load configuration from a `.env` file using environment variables: `BOX_DEV_TOKEN`, `AWS_REGION`, AWS credential chain, and `BEDROCK_MODEL_ID`.
7. IF a required environment variable is missing at startup, THEN THE GhostWriter CLI SHALL print a descriptive error message identifying the missing variable and exit with a non-zero status code.

---

### Requirement 2: Transcript Ingestion

**User Story:** As a developer, I want GhostWriter to upload transcript files to Box, so that Box AI can process them for task extraction.

#### Acceptance Criteria

1. WHEN `--transcripts <dir>` is provided, THE Pipeline SHALL read all `.txt` and `.md` files from the specified directory.
2. WHEN `--paste` is provided, THE Pipeline SHALL read transcript content from stdin and treat it as a single transcript.
3. THE Box_Client SHALL upload each transcript file to a designated Box folder and return the Box file ID for each uploaded file.
4. IF a transcript file cannot be read or uploaded, THEN THE Pipeline SHALL log the error with the filename and continue processing remaining transcripts.
5. THE Pipeline SHALL store the mapping of transcript filename to Box file ID for use in subsequent steps.

---

### Requirement 3: Task Extraction via Box AI

**User Story:** As a developer, I want GhostWriter to extract structured tasks from each transcript using Box AI, so that I have a machine-readable task list per meeting.

#### Acceptance Criteria

1. WHEN a transcript has been uploaded to Box, THE Box_Client SHALL call the Box AI Extract endpoint (`POST /2.0/ai/extract`, freeform) for that file.
2. THE Box_Client SHALL request extraction using the schema: `{title, description, owner, status_mentioned (todo|in_progress|blocked|done|unclear), is_action_item (bool)}`.
3. THE Pipeline SHALL store the raw extracted task JSON as a file in a Box `tasks/` folder, named after the source transcript.
4. IF the Box AI Extract call fails for a transcript, THEN THE Pipeline SHALL log the error with the transcript identifier and continue with remaining transcripts.
5. THE Pipeline SHALL collect all extracted Task objects for use in the recurrence step.

---

### Requirement 4: Recurrence Detection via Box AI

**User Story:** As a developer, I want GhostWriter to identify tasks that recur across multiple meetings but are never resolved, so that I can surface genuinely neglected work.

#### Acceptance Criteria

1. WHEN all transcripts have been extracted, THE Box_Client SHALL call the Box AI Ask endpoint (`POST /2.0/ai/ask`, multi-file mode) over all uploaded transcript file IDs.
2. THE Pipeline SHALL instruct Box AI to identify tasks mentioned across multiple meetings that have never moved to a `done` status and have no clear owner assignment.
3. THE Pipeline SHALL produce a list of NeglectedTask objects, each with a short reason string (e.g., "raised in 3 standups, still unassigned").
4. IF the Box AI Ask call fails, THEN THE Pipeline SHALL log the error and halt the pipeline with a non-zero exit code.
5. WHEN no neglected tasks are found, THE Pipeline SHALL log a message indicating no recurring neglected tasks were detected and produce an empty report.

---

### Requirement 5: Task Classification via Bedrock LLM

**User Story:** As a developer, I want GhostWriter to classify which neglected tasks are safe to auto-implement, so that only low-risk changes are attempted automatically.

#### Acceptance Criteria

1. THE Pipeline SHALL invoke a Bedrock LLM (model ID read from `BEDROCK_MODEL_ID` env var) via the Strands SDK to classify each NeglectedTask.
2. THE Pipeline SHALL set `auto_doable=true` ONLY for tasks that fall into these categories: fix typo, update doc or README, add missing log line, add null/empty check, bump a dependency version, add a simple unit test, rename for consistency.
3. THE Pipeline SHALL set `auto_doable=false` for any task that involves authentication, payments, database migrations, infrastructure changes, or code deletion.
4. THE Pipeline SHALL set `auto_doable=false` for any task that does not clearly fit the allowlisted categories.
5. IF the Bedrock classification call fails for a task, THEN THE Pipeline SHALL default that task to `auto_doable=false` and log the error.
6. THE Pipeline SHALL log the classification decision and reasoning for each task to stdout with the task identifier.

---

### Requirement 6: Repository Safety and Working Copy

**User Story:** As a developer, I want GhostWriter to never modify my original repository, so that automated changes cannot corrupt my codebase.

#### Acceptance Criteria

1. WHEN a `--repo <dir>` is provided, THE Orchestrator SHALL copy the target repository to a temporary working directory before any agent operates on it.
2. THE Orchestrator SHALL create a git feature branch named `ghostwriter/auto-<timestamp>` in the working copy before any changes are made.
3. THE Orchestrator SHALL push the feature branch to the GitHub remote after all Worker tasks are complete.
4. THE Orchestrator SHALL NEVER push directly to `main` or `master` and SHALL NEVER open a pull request automatically.
5. WHILE a Worker agent is executing, THE Worker SHALL only write files within the working copy directory.
6. IF a Worker attempts to write a file outside the working copy directory, THEN THE Worker tools SHALL reject the write and log a security violation.
7. THE Orchestrator SHALL commit Worker changes to the `ghostwriter/auto-<timestamp>` branch in the working copy after each successful task.

---

### Requirement 7: Orchestrator Agent

**User Story:** As a developer, I want a Strands orchestrator agent to coordinate task implementation, so that multiple tasks can be handled systematically.

#### Acceptance Criteria

1. THE Orchestrator SHALL be implemented using the AWS Strands Agents SDK with Amazon Bedrock as the model provider.
2. THE Orchestrator SHALL use the "agents-as-tools" multi-agent pattern, wrapping each Worker agent as a `@tool` function.
3. THE Orchestrator SHALL be given filesystem tools (`read_file`, `list_dir`, `grep`) to understand the target repository structure.
4. WHEN `--dry-run` is specified, THE Orchestrator SHALL NOT be invoked.
5. FOR each `auto_doable=true` NeglectedTask, THE Orchestrator SHALL invoke a Worker sub-agent to implement that task.
6. THE Orchestrator SHALL log each action to stdout with the associated task identifier.

---

### Requirement 8: Worker Agent

**User Story:** As a developer, I want each worker agent to implement a single task safely and return a verifiable result, so that I can review exactly what changed.

#### Acceptance Criteria

1. THE Worker SHALL be implemented using the AWS Strands Agents SDK with Amazon Bedrock as the model provider.
2. THE Worker SHALL be given tools: `read_file`, `write_file` (restricted to working copy), `grep`, and `run_shell` (allowlisted commands only).
3. WHEN implementing a task, THE Worker SHALL locate the relevant file(s), make the minimal required change, and run any available test or lint command.
4. THE Worker SHALL return a WorkerResult containing: a unified git diff, a 1-line summary, and a pass/fail status.
5. IF no test or lint command is found in the working copy, THE Worker SHALL skip that step and record it in the WorkerResult.
6. THE Worker SHALL log each action to stdout with the associated task identifier.
7. WHEN the target repository contains an existing test suite (e.g., `pytest`, `unittest`, `jest`), THE Worker SHALL run the full test suite after making changes and record the end-to-end pass/fail result in the WorkerResult.
8. IF the full test suite fails after a Worker's change, THE Worker SHALL record the failure in the WorkerResult and the Orchestrator SHALL revert that task's changes in the working copy.

---

### Requirement 9: Shell Command Safety

**User Story:** As a developer, I want shell command execution to be restricted to safe operations, so that agents cannot run arbitrary or destructive commands.

#### Acceptance Criteria

1. THE Worker tools SHALL maintain an allowlist of permitted shell command prefixes for `run_shell`: test runners (e.g., `pytest`, `python -m pytest`), linters (e.g., `flake8`, `ruff`, `eslint`), and build commands (e.g., `make test`, `npm test`).
2. IF a `run_shell` call uses a command not on the allowlist, THEN THE Worker tools SHALL reject the call, log a security violation with the attempted command, and return an error to the Worker.
3. THE Worker tools SHALL execute all `run_shell` commands with the working copy as the working directory.

---

### Requirement 10: Run Report

**User Story:** As a developer, I want a Markdown run report summarizing the pipeline results, so that I can review what was found and what was changed.

#### Acceptance Criteria

1. THE Pipeline SHALL aggregate all results into a RunReport containing: neglected tasks found, which tasks were auto-attempted, the git diff for each attempted task, test/lint status per task, and the report-only (non-auto_doable) tasks.
2. THE Pipeline SHALL print the RunReport to stdout in Markdown format.
3. THE Box_Client SHALL upload the RunReport as a Markdown file to a Box `reports/` folder.
4. IF the Box upload of the report fails, THEN THE Pipeline SHALL log the error but still print the report to stdout and exit with a non-zero status code.
5. WHEN `--dry-run` is specified, THE RunReport SHALL include only the neglected-task list, reasons, and auto_doable shortlist (no diffs or test results).

---

### Requirement 11: Logging and Observability

**User Story:** As a developer, I want all agent actions logged to stdout with task identifiers, so that I can follow the reasoning during a demo.

#### Acceptance Criteria

1. THE GhostWriter CLI SHALL log each pipeline step start and completion to stdout.
2. THE Orchestrator SHALL log each agent action to stdout prefixed with the task identifier.
3. THE Worker SHALL log each tool call (read, write, grep, shell) to stdout prefixed with the task identifier.
4. THE Pipeline SHALL log Box AI call start, completion, and any errors to stdout.
5. THE Pipeline SHALL log Bedrock classification decisions and reasoning to stdout with the task identifier.

---

### Requirement 12: Project Structure and Configuration

**User Story:** As a developer, I want the project to follow a standardized file structure and configuration pattern, so that it is easy to maintain and extend with a UI later.

#### Acceptance Criteria

1. THE GhostWriter project SHALL be structured with these files: `main.py`, `box_client.py`, `pipeline.py`, `agents/orchestrator.py`, `agents/worker.py`, `agents/tools.py`, `models.py`, `.env.example`, `README.md`, `pyproject.toml`.
2. THE GhostWriter project SHALL use Python 3.11+ and be packaged with `uv` (with `venv + pip` as a documented fallback).
3. THE GhostWriter project SHALL include a `.env.example` file listing all required environment variables with placeholder values and comments.
4. THE GhostWriter project SHALL include a `sample/` directory with at least 3 fake standup transcripts that reference the same recurring task across all 3, and a `sample_repo/` directory with minimal code files for end-to-end demo use.
5. THE README SHALL document all assumptions, setup steps, and the CCG upgrade path for Box authentication.
6. THE GhostWriter project SHALL use `BEDROCK_MODEL_ID` from the environment and SHALL NOT hardcode any model identifier string in source code.
