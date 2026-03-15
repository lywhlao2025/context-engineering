# Context-Engineering

Build and maintain team-style project context directories for AI agents.

This repository packages a local agent skill (`SKILL.md`) plus two Python scripts:

- `scripts/init_context_project.py` creates the initial context scaffold.
- `scripts/sync_context_project.py` refreshes generated context blocks with Git-aware sync behavior.

The goal is to keep project context lightweight, navigable, and safe to update over time without overwriting manual notes.

## What It Does

- Scaffolds a project context workspace under `~/clawDir/team` by default.
- Accepts either a local checkout (`--code-dir`) or a Git source (`--git-url`).
- Infers module buckets such as `frontend`, `backend`, `qa`, `mobile`, `data`, `ops`, and `reviewer`.
- Creates project-level docs, per-module docs, per-feature docs inside technical modules, and per-agent folders.
- Fills agent docs (`agents.md`, per-agent `README.md`, `tools.md`, `memory.md`) during sync so sub-agents have real initialization context.
- Builds a requirements trace map (`references/requirements-map.md`) from PRD docs under `references/prd.md` or `references/prd/*.md`.
- Uses Git-first incremental sync only from a clean checked-out default branch (`main` or `master`) when a valid prior sync state exists.
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
    ├── source_resolver.py
    └── sync_context_project.py
```

- `SKILL.md`: the agent-facing workflow and rules for using this skill.
- `scripts/context_layout.py`: shared layout constants and path helpers.
- `scripts/init_context_project.py`: idempotent scaffold generator.
- `scripts/source_resolver.py`: resolves either a local code directory or a managed Git clone under the target root.
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

Initialize from Git instead of a local checkout:

```bash
python3 scripts/init_context_project.py \
  --project my-project \
  --git-url https://github.com/example/my-project.git
```

Sync generated context after the scaffold exists:

```bash
python3 scripts/sync_context_project.py \
  --project my-project \
  --code-dir /absolute/path/to/my-project
```

Sync against a managed Git clone:

```bash
python3 scripts/sync_context_project.py \
  --project my-project \
  --git-url https://github.com/example/my-project.git
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
  (--code-dir <absolute-code-dir> | --git-url <git-url>) \
  [--target-root <context-root>]
```

Behavior:

- Creates missing directories and files only.
- When `--git-url` is used, clones the repository into `<target-root>/sources/<project-name>` and analyzes that managed checkout.
- Updates `projects/projects.md` with the new project entry.
- Infers initial modules from the code tree.
- Creates placeholder module docs and agent folders.

### `sync_context_project.py`

```bash
python3 scripts/sync_context_project.py \
  --project <project-name> \
  (--code-dir <absolute-code-dir> | --git-url <git-url>) \
  [--target-root <context-root>] \
  [--dry-run] \
  [--force-generated] \
  [--review-outcome <pending|pass|pass-with-findings|fail>] \
  [--review-notes "<summary>"]
```

Flags:

- `--dry-run`: print planned updates without writing files.
- `--force-generated`: overwrite conflicting generated `AUTO` blocks.
- `--review-outcome`: record the review result for the current sync snapshot.
- `--review-notes`: optional short note to store with the recorded review result.

`--dry-run` with `--git-url` requires an existing managed checkout. It will not clone or fetch sources.

## How Sync Works

`sync_context_project.py` chooses one of three modes:

- `incremental`: Git repo with valid sync state and safely scoped changes.
- `full`: initial sync, non-Git repo, module drift, unmatched paths, or broad changes.
- `noop`: no code changes detected since the last successful sync.

For Git repos, sync only runs when:

- the checked-out branch is `main` or `master`
- the worktree is clean, including untracked files

The local checked-out default branch is treated as the source of truth. Incremental diffs are computed from the last synced default-branch commit to the current `HEAD` on that same branch.

When `--git-url` is used, the tool maintains a managed checkout at:

```text
<target-root>/sources/<project>
```

That managed checkout is fetched and fast-forwarded before analysis. If it becomes dirty or stops matching the configured `origin`, sync stops instead of mutating it blindly.

Once a project context has been created, sync keeps it bound to the same source. Reusing the same `--project` name with a different local checkout or Git URL is rejected.

Sync state is stored in:

```text
<target-root>/projects/<project>/.context-sync/state.json
```

The state file now tracks the review result as machine-readable metadata. Any sync with code changes resets the recorded outcome to `pending` until a new `pass`, `pass with findings`, or `fail` result is recorded.

The sync currently updates generated `AUTO` blocks in:

- `skill.md`
- `agents/agents.md`
- `agents/<agent>/README.md`
- `agents/<agent>/tools.md`
- `agents/<agent>/memory.md`
- `modules/README.md`
- `modules/<module>/README.md`
- `modules/<module>/<module>.md`
- `modules/<module>/<feature>.md`
- `references/entrypoints.md`
- `references/feature-map.md`
- `references/requirements-map.md`
- `project_status.md`

Manual content outside those blocks is preserved.

## Review Model

Generation is not considered complete until the context is reviewed.

The review workflow is intentionally Git-first:

1. Inspect Git diff/tree or the sync output first.
2. Route through the task-matched agent, then spot-check only the changed modules when diff-only review is safe.
3. Within a changed technical module, load the matching feature docs when stable business slices exist.
4. Broaden to source-level review only when the context is new, ambiguous, or out of sync with the diff scope.

After review, record the result through `--review-outcome` so the sync state is no longer left in `pending`.

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
├── sources/
│   └── <project>/   # optional managed Git checkout when --git-url is used
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
        │       ├── <module>.md
        │       └── <feature>.md   # optional business-slice doc under a technical module
        ├── references/
        │   ├── entrypoints.md
        │   ├── feature-map.md
        │   └── requirements-map.md
        └── .context-sync/
            └── state.json
```

## Notes And Limits

- Git sync refuses to run on non-default branches or dirty worktrees.
- Managed Git sources must expose `main` or `master` for analysis.
- The tool does not auto-checkout or pull user-owned local checkouts. Managed Git sources under `<target-root>/sources/` may be fetched and fast-forwarded.
- Incremental review depends on a trustworthy Git baseline.
- If generated `AUTO` blocks are edited manually, sync will stop unless forced.
- Generated AUTO content now includes file/symbol evidence samples (with line hints when available), but it is still heuristic and should be validated during the mandatory review pass.
- Feature inference is also heuristic; if the repo does not expose stable business boundaries in its paths and filenames, the generated feature docs will be sparse until the user adds manual guidance.
- Requirement-to-code mapping is heuristic; keep PRD docs structured (clear requirement IDs and acceptance bullets) to improve matching quality.

## Positioning

This repository is best treated as a context-maintenance utility for local agent workflows:

- `SKILL.md` defines the operating contract for the agent.
- The Python scripts implement the filesystem and sync behavior behind that contract.

If you want to use the skill from an agent environment, load `SKILL.md`. If you want to use the functionality directly, run the Python scripts.
