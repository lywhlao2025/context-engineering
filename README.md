# Context-Engineering

Build and maintain team-style project context directories for AI agents.

This repository packages a local agent skill (`SKILL.md`) plus two Python scripts:

- `scripts/init_context_project.py` creates the initial context scaffold.
- `scripts/sync_context_project.py` refreshes generated context blocks with Git-aware sync behavior.

The goal is to keep project context lightweight, navigable, and safe to update over time without overwriting manual notes.

## What It Does

- Scaffolds a project context workspace under `~/clawDir/team` by default.
- Infers module buckets such as `frontend`, `backend`, `qa`, `mobile`, `data`, `ops`, and `reviewer`.
- Creates project-level docs, per-module docs, and per-agent folders.
- Uses Git-first incremental sync when a valid prior sync state exists.
- Falls back to full sync when the repo is non-Git, the module map changes, or the diff is too broad.
- Rewrites only managed `AUTO` blocks so manual notes outside those blocks survive syncs.
- Refuses to overwrite manually edited generated blocks unless `--force-generated` is passed.

## Repository Layout

```text
.
├── SKILL.md
├── README.md
├── references/
│   └── extraction-rules.md
└── scripts/
    ├── context_layout.py
    ├── init_context_project.py
    └── sync_context_project.py
```

- `SKILL.md`: the agent-facing workflow and rules for using this skill.
- `scripts/context_layout.py`: shared layout constants and path helpers.
- `scripts/init_context_project.py`: idempotent scaffold generator.
- `scripts/sync_context_project.py`: incremental/full sync engine with review planning.
- `references/extraction-rules.md`: detailed extraction rules for entrypoints, flows, data, tests, and i18n.

## Requirements

- Python 3.10+
- Git, if you want incremental sync and Git-based review scope
- No third-party Python dependencies

Python 3.11+ is recommended because `pyproject.toml` inspection uses the standard-library `tomllib` module when available.

## Quick Start

Initialize a new project context:

```bash
python3 scripts/init_context_project.py \
  --project my-project \
  --code-dir /absolute/path/to/my-project
```

Sync generated context after the scaffold exists:

```bash
python3 scripts/sync_context_project.py \
  --project my-project \
  --code-dir /absolute/path/to/my-project
```

Use a custom target root instead of `~/clawDir/team`:

```bash
python3 scripts/init_context_project.py \
  --project my-project \
  --code-dir /absolute/path/to/my-project \
  --target-root /absolute/path/to/team
```

## CLI Reference

### `init_context_project.py`

```bash
python3 scripts/init_context_project.py \
  --project <project-name> \
  --code-dir <absolute-code-dir> \
  [--target-root <context-root>]
```

Behavior:

- Creates missing directories and files only.
- Updates `projects/projects.md` with the new project entry.
- Infers initial modules from the code tree.
- Creates placeholder module docs and agent folders.

### `sync_context_project.py`

```bash
python3 scripts/sync_context_project.py \
  --project <project-name> \
  --code-dir <absolute-code-dir> \
  [--target-root <context-root>] \
  [--dry-run] \
  [--include-untracked] \
  [--force-generated]
```

Flags:

- `--dry-run`: print planned updates without writing files.
- `--include-untracked`: include untracked files in Git change detection.
- `--force-generated`: overwrite conflicting generated `AUTO` blocks.

## How Sync Works

`sync_context_project.py` chooses one of three modes:

- `incremental`: Git repo with valid sync state and safely scoped changes.
- `full`: initial sync, non-Git repo, module drift, unmatched paths, or broad changes.
- `noop`: no code changes detected since the last successful sync.

Sync state is stored in:

```text
<target-root>/projects/<project>/.context-sync/state.json
```

The sync currently updates generated `AUTO` blocks in:

- `skill.md`
- `modules/README.md`
- `modules/<module>/README.md`
- `modules/<module>/<module>.md`
- `references/entrypoints.md`
- `project_status.md`

Manual content outside those blocks is preserved.

## Review Model

Generation is not considered complete until the context is reviewed.

The review workflow is intentionally Git-first:

1. Inspect Git diff/tree or the sync output first.
2. Spot-check only the changed modules when diff-only review is safe.
3. Broaden to source-level review only when the context is new, ambiguous, or out of sync with the diff scope.

Review scope is reported as one of:

- `git-diff-only`
- `broad-source-review`
- `noop`

This keeps context maintenance targeted instead of re-reading the full codebase on every sync.

## Generated Context Layout

The scaffold produces a structure like this:

```text
<target-root>/
├── readme.md
└── projects/
    ├── projects.md
    └── <project>/
        ├── readme.md
        ├── goals.md
        ├── skill.md
        ├── project_status.md
        ├── decisions.md
        ├── agents/
        │   ├── agents.md
        │   └── <agent>/
        │       ├── README.md
        │       ├── tools.md
        │       ├── memory.md
        │       ├── decisions.jsonl
        │       └── fails.jsonl
        ├── modules/
        │   ├── README.md
        │   └── <module>/
        │       ├── README.md
        │       └── <module>.md
        ├── references/
        │   └── entrypoints.md
        └── .context-sync/
            └── state.json
```

## Notes And Limits

- Agent folders are scaffolded during init, but the sync script does not currently regenerate agent docs.
- The tool does not auto-checkout branches or pull remote changes.
- Incremental review depends on a trustworthy Git baseline.
- If generated `AUTO` blocks are edited manually, sync will stop unless forced.

## Positioning

This repository is best treated as a context-maintenance utility for local agent workflows:

- `SKILL.md` defines the operating contract for the agent.
- The Python scripts implement the filesystem and sync behavior behind that contract.

If you want to use the skill from an agent environment, load `SKILL.md`. If you want to use the functionality directly, run the Python scripts.
