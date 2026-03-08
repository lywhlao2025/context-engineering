---
name: context-engineering
description: Build or initialize team-style project context directories for context engineering. Use when the user says “构建/初始化项目上下文”, “针对该项目构建上下文”, or asks to scaffold a project context under a specified target directory (default ~/clawDir/team).
---

# Context Engineering

## Overview

Create a consistent project context structure (team navigation + project folder) and link it to a code directory. Default target root is `~/clawDir/team`, but allow the user to specify another root path.

## Loading Model (L1/L2/L3)

- **L1**: Project `skill.md` — global overview, module navigation, environment notes.
- **L2**: `modules/` — task-scoped module docs. Load the module overview first, then specific submodules.
- **L3**: `references/` — entrypoints, API indices, migrations, evidence-level docs.

## Workflow

1. **Collect inputs**
   - `project_name` (folder name)
   - `code_dir` (absolute path to the code)
   - `target_root` (optional). If not provided, use `~/clawDir/team`.

2. **Analyze the code structure**
   - Identify tech stack and main areas (frontend/backend/qa/etc.) from code directory structure and key files.

3. **Initialize the context structure**
   - Prefer running the bundled script:
     ```bash
     python scripts/init_context_project.py \
       --project <project_name> \
       --code-dir <code_dir> \
       --target-root <target_root>
     ```
   - The script infers module buckets from the codebase and creates module folders dynamically.
   - The script is idempotent: it won’t overwrite existing files.

4. **Post-init checks**
   - Verify the created files exist under: `<target_root>/projects/<project_name>/`.
   - If the user wants custom content, edit `readme.md`, `goals.md`, and `project_status.md` accordingly.

## Modules Directory Guidance

- `modules/` is generated based on the target codebase (not fixed).
- Recommended buckets: `frontend`, `backend`, `qa`, `reviewer` (only if inferred).
- Each module may contain multiple detailed docs; keep an overview `modules/<module>/README.md` and a `modules/<module>/<module>.md` for detailed module notes.

## Generation Rules (Modules & Agents)

### Modules
- Each module folder must include:
  - `modules/<module>/README.md` (overview)
  - `modules/<module>/<module>.md` (details: Scope, Key Responsibilities, Important Notes, Interfaces & Dependencies)

### Agents
- Create one folder per agent under `agents/<agent>/`.
- Each agent folder must include `README.md` with:
  - Focus / responsibilities
  - Key files
  - Notes or checklists relevant to that role

## Files Created

- `<target_root>/readme.md` (if missing)
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

## Resources

- `scripts/init_context_project.py` — scaffold generator (preferred).
