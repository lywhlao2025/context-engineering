---
name: context-engineering
description: Build or initialize team-style project context directories for context engineering. Use when the user says “构建/初始化项目上下文”, “针对该项目构建上下文”, **or** in English phrases like “build/initialize project context”, “scaffold project context”, “set up project context docs”, “create project context”, “generate project context docs”, “initialize context engineering project”, “set up team context”, “build context workspace”, or asks to scaffold a project context under a specified target directory (default ~/clawDir/team).
---

# Context Engineering

## Overview

Create a consistent project context structure (team navigation + project folder) and link it to a code directory. Default target root is `~/clawDir/team`, but allow the user to specify another root path.

Use a two-stage model:

- `scripts/init_context_project.py` creates missing scaffold files and folders only.
- `scripts/sync_context_project.py` refreshes generated context content after the scaffold exists.
- Generation is not complete until the generated context has been reviewed with a **Git-first** workflow and obvious issues have been fixed or explicitly called out.

## Loading Model (L1/L2/L3)

- **L1**: Project `skill.md` — global overview, module navigation, environment notes.
- **L2**: `modules/` + `agents/` — task-scoped module docs **and** agent role docs. Load the module overview first, then specific submodules; load the relevant agent README when working on that role’s tasks.
- **L3**: `references/` — entrypoints, API indices, migrations, evidence-level docs.

## Workflow

1. **Collect inputs**
   - `project_name` (folder name)
   - Source input: either `code_dir` (absolute path to the code) or `git_url` (Git URL or local Git repo path to clone)
   - `target_root` (optional). If not provided, use `~/clawDir/team`.

2. **Analyze the code structure**
   - If `git_url` is provided, prepare a managed checkout under `<target_root>/sources/<project_name>` before analysis.
   - First build or missing sync state: identify tech stack and main areas (frontend/backend/qa/etc.) from code directory structure and key files.
   - Existing Git-backed context: start from Git diff/tree first; do **not** broad-read the source tree before you know the changed scope.
   - Read top-level docs such as `README*`, `docs/`, `tech.md`, `architecture.md`, `CHANGELOG*` when bootstrapping a project or when a broad review trigger fires.

3. **Initialize the context structure**
   - Prefer running the bundled script:
     ```bash
     python scripts/init_context_project.py \
       --project <project_name> \
       --code-dir <code_dir> | --git-url <git_url> \
       --target-root <target_root>
     ```
   - The script infers module buckets from the codebase and creates module folders dynamically.
   - If `git_url` is used, the script clones the repo into `<target_root>/sources/<project_name>` and analyzes that managed checkout.
   - The script is idempotent: it won’t overwrite existing files.

4. **Sync generated context content**
   - Prefer running the bundled script:
     ```bash
     python scripts/sync_context_project.py \
       --project <project_name> \
       --code-dir <code_dir> | --git-url <git_url> \
       --target-root <target_root>
     ```
   - If `git_url` is used, the script refreshes the managed checkout under `<target_root>/sources/<project_name>` before diffing.
   - `--dry-run` with `git_url` requires an existing managed checkout; it must not clone or fetch sources.
   - `Git` project: sync only from a clean checked-out default branch (`main` or `master`).
   - Incremental sync compares the current default-branch `HEAD` against the last successful sync head recorded for that same local default branch.
   - Non-`Git` project: full sync only.
   - If the checked-out branch is not `main` or `master`, stop and ask the user to switch to the default branch before syncing.
   - If the worktree is not clean, stop and ask the user to commit, stash, or remove local changes before syncing.
   - If the sync state is missing, invalid, the previous sync head is not usable on the current default branch, or the module map changed, the sync falls back to a full refresh.
   - Once a project context exists, keep it bound to the same source. If the user wants to analyze a different repo, use a new `project_name`.
   - Sync only updates managed `AUTO` blocks. Manual notes outside those blocks are preserved.
   - If a managed `AUTO` block was edited manually after the last sync, the sync stops unless `--force-generated` is passed.
   - Treat the sync output as the default review plan input: `changed_paths`, `changed_modules`, `sync mode`, and `review scope`.

5. **Review and extend content (mandatory)**
   - Fill `skill.md` (L1) with **project summary, architecture, entrypoints, build/run, module navigation**.
   - Fill `modules/<module>/README.md` (overview) and `modules/<module>/<module>.md` (detail).
   - Fill `references/entrypoints.md` with code-level entrypoints and indexes.
   - Follow this review order strictly:
     1. Inspect Git diff/tree or the sync output first.
     2. Spot-check only the modules hit by the diff.
     3. Broaden to a wider source review only when one of these triggers fires:
        - first context build / no previous sync state
        - module map changed
        - runtime entrypoint judgment is ambiguous
        - the existing context does not match the diff scope
        - non-Git repo, because no diff baseline exists
   - If sync reports `Review scope: noop`, do not re-read source files.
   - In targeted review mode, at minimum review only the diff-hit scope for:
     - runtime entrypoints vs build/config files inside the changed scope
     - module boundaries vs actual functional boundaries inside the changed scope
     - QA/test/release/storage/i18n coverage touched by the diff
     - inconsistencies between manual notes and generated `AUTO` blocks for the changed scope
     - obvious stale status fields such as `project_status.md`
   - In broad review mode, expand the same checks to the wider source tree.
   - Fix clear issues immediately. If an issue cannot be fixed safely in the current turn, report it explicitly as a review finding.

6. **Post-review checks**
   - Verify the created files exist and are filled under: `<target_root>/projects/<project_name>/`.
   - Re-run sync if review-driven edits changed managed generation rules or `AUTO` content.
   - If the user wants custom content, update modules and references accordingly.
   - Record major changes in `decisions.md` (project-level) or `decisions.jsonl` (agent-level).

## Sync Model

- Sync state lives at `<target_root>/projects/<project_name>/.context-sync/state.json`.
- The state file records the last successful sync snapshot, module map, watched global paths, hashes for generated `AUTO` blocks, the last synced default-branch head, and source metadata.
- Incremental sync is attempted only for `Git` projects with a valid state file and a clean checked-out default branch (`main` or `master`).
- Incremental sync uses the local checked-out default branch as the source of truth. It must not auto-checkout another branch or auto-pull, because that would mutate the user's repo state.
- For managed `git_url` sources under `<target_root>/sources/<project_name>`, the skill may fetch and fast-forward the managed checkout before analysis.
- Non-`Git` projects always use full sync because there is no reliable diff baseline.
- Large or ambiguous `Git` changes fall back to full sync rather than risking stale context.
- Incremental review is Git-first: start from the default-branch diff/tree, then read only the affected modules unless a broad review trigger fires.

### Review Scope Meanings

- `git-diff-only`: first inspect Git diff/tree, then spot-check only the modules and paths hit by the diff.
- `broad-source-review`: widen back to the source tree because diff-only review is not safe enough for this run.
- `noop`: no code changes were detected, so do not re-read source files.

## Ownership Rules

- Manual content is user-owned. Put it outside managed `AUTO` blocks.
- Generated content is sync-owned. `sync_context_project.py` rewrites only those `AUTO` blocks.
- If a generated `AUTO` block is edited manually, that is treated as a conflict on the next sync.
- Use `--force-generated` only when you intentionally want the sync to replace the current generated block.

## Mandatory Review Standard

- Every generated or synced project context must receive a review pass before the task is considered complete.
- The default review path is **not** a broad source reread. Start from Git diff/tree and compare generated docs against the affected scope first.
- Broader source review is reserved for these triggers:
  - first build or missing sync state
  - module map drift
  - ambiguous entrypoints or runtime/build boundaries
  - context vs diff mismatch
  - non-Git repos
- Prioritize finding misleading context over producing more text. Typical failure modes:
  - config or package files misclassified as runtime entrypoints
  - major functional areas missing from modules
  - QA/release/storage/i18n concerns missing or under-modeled
  - agent docs left as placeholders
  - status files that no longer match the real project state
- Review outcomes must be one of:
  - `pass`: context is accurate enough to hand off
  - `pass with findings`: mostly usable, but known issues are called out
  - `fail`: generated context is materially misleading and needs fixes before handoff
- If the user explicitly asks for a review, present findings first with concrete file references.

## Modules Directory Guidance

- `modules/` is generated based on the target codebase (not fixed).
- Recommended buckets: `frontend`, `backend`, `qa`, `reviewer` (only if inferred).
- Each module may contain multiple detailed docs; keep an overview `modules/<module>/README.md` and a `modules/<module>/<module>.md` for detailed module notes.
- If a domain is present (e.g., `mobile`, `data`, `ops`, `infra`), create that module.

## Generation Rules (Modules & Agents)

### Modules

- Each module folder must include:
  - `modules/<module>/README.md` (overview)
  - `modules/<module>/<module>.md` (details: Scope, Key Responsibilities, Important Notes, Interfaces & Dependencies)
- If a module is large, split into multiple files (e.g., `A.md`, `B.md`, `C.md`). In that case, `<module>.md` becomes an index/summary that describes each sub-file and when to load it.

### Agents

- Create one folder per agent under `agents/<agent>/`.
- Agent list is inferred from module buckets; always include `reviewer`.
- Each agent folder must include:
  - `README.md` with Role, Principles, Responsibilities, Deliverables, Working Style, Notes
  - `tools.md` (Markdown)
  - `memory.md` (Markdown)
  - `decisions.jsonl` (JSONL, one decision per line)
  - `fails.jsonl` (JSONL, one failure per line)
- **README.md must also include a brief description of the purpose of other files in the current agent directory.**

## Content Extraction Rules (General)

Keep SKILL.md lean. For detailed extraction guidance (entrypoints, flows, data, tests, i18n), load:

- `references/extraction-rules.md`

## Output Templates (Required)

### L1 (skill.md)

- Project summary (what it is + target users)
- Architecture & boundaries
- Entrypoints + build/run
- Module navigation
- Progressive loading model (L1/L2/L3)
- **Spec-driven development**
  - Spec-first rule (no implementation without a spec)
  - Spec template (scope, interfaces, edge cases/errors, acceptance criteria, tests)
  - Change control (spec updates recorded in decisions)
  - Traceability (code/tests map back to spec items)
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

### L2 (modules/<module>/README.md)

- Responsibilities
- Key areas/files
- Typical tasks
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

### L2 (modules/<module>/<module>.md)

- Scope
- Key Responsibilities
- Important Notes (constraints, risks, decisions)
- Interfaces & Dependencies
- Key flows (if applicable)
- Testing/QA hooks
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

### L2 (agents/<agent>/README.md)

- Role
- Principles
- Responsibilities
- Deliverables
- Working Style
- Notes
- Description of other files in the agent directory

### L3 (references/entrypoints.md)

- Entry file index
- Core logic/index files
- Data/storage index
- i18n index
- Build/release/ops entrypoints
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## Quality Checklist (Before Finalizing)

- L1 filled with accurate architecture and run/build info
- Each module has README + <module>.md
- References contain concrete file paths
- Loading paths cover UI/UX, core logic, QA, release scenarios
- Agent folders exist with clear responsibilities
- Mandatory review completed after generation/sync
- No unresolved placeholder `TODO` content in delivered context unless explicitly marked as pending
- Runtime entrypoints are separated from build/config/release files
- Major functional modules in the codebase are represented in context, either as top-level modules or documented submodules
- `project_status.md` and other summary files do not obviously contradict the current project state

## Files Created

- `<target_root>/readme.md` (if missing)
- `<target_root>/sources/<project_name>/` (when `git_url` is used)
- `<target_root>/projects/projects.md` (index with new project entry)
- `<target_root>/projects/<project_name>/readme.md`
- `<target_root>/projects/<project_name>/goals.md`
- `<target_root>/projects/<project_name>/skill.md`
- `<target_root>/projects/<project_name>/project_status.md`
- `<target_root>/projects/<project_name>/decisions.md`
- `<target_root>/projects/<project_name>/agents/agents.md`
- `<target_root>/projects/<project_name>/modules/README.md`
- `<target_root>/projects/<project_name>/modules/<module>/README.md` (modules inferred from code)
- `<target_root>/projects/<project_name>/modules/<module>/<module>.md`
- `<target_root>/projects/<project_name>/references/entrypoints.md`
- `<target_root>/projects/<project_name>/.context-sync/state.json`

## Resources

- `scripts/init_context_project.py` — scaffold generator (preferred).
- `scripts/sync_context_project.py` — sync generator for Git incremental / non-Git full refresh.
