# ReviewAgent

> An evidence-driven, permission-scoped multi-agent runtime for code review.

ReviewAgent is a Python 3.11+ portfolio project that turns an LLM-assisted code review into an auditable workflow. It separates planning from execution, restricts each role to a small toolset, preserves code and rule evidence for every finding, and writes an append-only execution ledger that can be rendered into a report.

## Why this project

Most agent demos can produce a conclusion but cannot show **what the model read, why it was allowed to read it, or whether a reported line has supporting evidence**. ReviewAgent focuses on those engineering constraints:

- **Least-privilege roles**: the Planner can only submit task-graph commands; Executors receive read-only repository tools plus finding/result submission tools.
- **Evidence gate**: a finding must cite a source artifact that covers its file and line range. Security findings in RAG mode additionally require rule evidence.
- **Path safety**: every file tool checks the repository scope after real-path resolution and rejects absolute paths, traversal attempts, `.env`, and `.git` access.
- **Auditable state**: tool calls and submissions are appended to `execution.jsonl`; reports and metrics are projections from that ledger.
- **Dependency-aware execution**: the Controller atomically claims ready tasks and runs independent Executor tasks in a bounded thread pool (default: two), while Planner decisions stay serial.

## Architecture

```text
CLI
 └─ ReviewController
     ├─ Planner: planner_submit → validates and updates the task graph
     ├─ TaskStore: atomically claims dependency-ready tasks as running
     └─ Executor pool: read-only tools / finding_write / task_result_submit
          ├─ ArtifactStore: content-addressed code and rule evidence (SHA-256)
          ├─ FindingStore + evidence validation
          └─ ExecutionLog: append-only execution.jsonl

Optional RAG path: rule query → Dense retrieval + BM25 → reciprocal-rank fusion → rule evidence artifact
```

## Stack

- Python 3.11+, standard-library `urllib` for OpenAI-compatible LLM calls
- Qdrant client for vector retrieval; handwritten BM25 and reciprocal-rank fusion
- pytest for runtime, evidence-gate, retrieval, report, and local-workbench tests
- No orchestration framework: tool schemas, validation, retries, and persisted state are explicit in the codebase

## Quick start

```bash
# Create a virtual environment, then install the project and development dependencies.
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# Run the automated tests.
.venv\Scripts\python -m pytest -q --basetemp .tmp/pytest

# Run the deterministic local demo (no API key required).
.venv\Scripts\python -m review_agent --repo fixtures/demo-repo --scope src \
  --goal "Review the demo repository for code-quality and security issues" \
  --provider fake --max-cycles 6 --cases fixtures/cases.json

# Generate a read-only report from a completed run.
.venv\Scripts\python scripts/generate_report.py runs/<session-id>

# Browse local run reports (binds to localhost only).
.venv\Scripts\python -m review_agent.web
```

The fake provider exists to make the fixture workflow reproducible; its fixture score is **not** a claim about real-model performance. To use a compatible model, copy `.env.example` to a local `.env`, set the LLM variables, and select `--provider openai`.

## Retrieval and knowledge sources

The repository contains curated rule definitions and evaluation cases. Raw CWE and OWASP source snapshots, normalized outputs, Qdrant collections, API keys, and run artifacts stay local. Rebuild them explicitly when needed:

```bash
.venv\Scripts\python scripts/download_cwe.py
.venv\Scripts\python scripts/build_cwe_chunks.py knowledge/raw/cwe/<version>
.venv\Scripts\python scripts/download_owasp_cheatsheets.py
.venv\Scripts\python scripts/build_owasp_chunks.py knowledge/raw/owasp-cheatsheets/<commit>
.venv\Scripts\python scripts/index_rules.py
```

See [knowledge/README.md](knowledge/README.md) for source attribution, ingestion boundaries, and retrieval-evaluation format.

## Project layout

```text
review_agent/       Runtime: controller, roles, tools, stores, RAG, and localhost workbench
fixtures/           Deterministic demo repository and expected findings
knowledge/          Curated rule metadata, source manifests, and evaluation cases
scripts/            Evaluation, report generation, indexing, and source-ingestion utilities
tests/              Automated regression tests
```

## Scope and limitations

This is a local runtime, not a hosted code-review service. It does not post GitHub pull-request comments, execute untrusted code in a sandbox, or provide distributed scheduling/recovery. The bounded Executor pool overlaps independent I/O-bound work in one process; it is not distributed execution.

## License

MIT. See [LICENSE](LICENSE).
