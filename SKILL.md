---
name: context-engineering
description: Build or initialize team-style project context directories for context engineering. Use when the user says “构建/初始化项目上下文”, “针对该项目构建上下文”, or asks to scaffold a project context under a specified target directory (default ~/clawDir/team).
---

# Context Engineering

## Overview

Create a consistent project context structure (team navigation + project folder) and link it to a code directory. Default target root is `~/clawDir/team`, but allow the user to specify another root path.

## Loading Model (L1/L2/L3)

- **L1**: Project `skill.md` — global overview, module navigation, environment notes.
- **L2**: `modules/` + `agents/` — task-scoped module docs **and** agent role docs. Load the module overview first, then specific submodules; load the relevant agent README when working on that role’s tasks.
- **L3**: `references/` — entrypoints, API indices, migrations, evidence-level docs.

## Workflow

1. **Collect inputs**
   - `project_name` (folder name)
   - `code_dir` (absolute path to the code)
   - `target_root` (optional). If not provided, use `~/clawDir/team`.

2. **Analyze the code structure**
   - Identify tech stack and main areas (frontend/backend/qa/etc.) from code directory structure and key files.
   - Read top-level docs: `README*`, `docs/`, `tech.md`, `architecture.md`, `CHANGELOG*` if present.

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

4. **Populate content (critical)**
   - Fill `skill.md` (L1) with **project summary, architecture, entrypoints, build/run, module navigation**.
   - Fill `modules/<module>/README.md` (overview) and `modules/<module>/<module>.md` (detail).
   - Fill `references/entrypoints.md` with code-level entrypoints and indexes.

5. **Post-init checks**
   - Verify the created files exist and are filled under: `<target_root>/projects/<project_name>/`.
   - If the user wants custom content, update modules and references accordingly.

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

### Entrypoints & Runtime

- Find entry files (`main`, `index`, `app`, `server`) in the language/framework.
- Capture build/run scripts from package/config files (e.g., `package.json`, `Makefile`, `pyproject.toml`, `pom.xml`).
- Note extension or deployment entrypoints (e.g., `manifest.json`, `Dockerfile`, `helm/`).

### Core Flows

- Identify primary user flows or API flows and map to modules.
- For each flow, note: input → processing → output, plus error handling.

### Data & Storage

- Note persistence mechanisms (DB, localStorage, files, caches), migration paths, and data schemas.

### Testing & QA

- Find test directories, frameworks, and critical test cases.
- Summarize how to run tests and what scenarios are essential.

### i18n / Localization

- Detect locale files and string sources; note sync requirements between app strings and platform-specific locales.

## Output Templates (Required)

### L1 (skill.md)

- Project summary (what it is + target users)
- Architecture & boundaries
- Entrypoints + build/run
- Module navigation
- Progressive loading model (L1/L2/L3)

### L2 (modules/<module>/README.md)

- Responsibilities
- Key areas/files
- Typical tasks

### L2 (modules/<module>/<module>.md)

- Scope
- Key Responsibilities
- Important Notes (constraints, risks, decisions)
- Interfaces & Dependencies
- Key flows (if applicable)
- Testing/QA hooks

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

## Quality Checklist (Before Finalizing)

- L1 filled with accurate architecture and run/build info
- Each module has README + <module>.md
- References contain concrete file paths
- Loading paths cover UI/UX, core logic, QA, release scenarios
- Agent folders exist with clear responsibilities

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
