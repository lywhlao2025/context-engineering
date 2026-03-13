# Structure Rules

Use this reference when you need the detailed project-context structure rules for modules and agents.

## Agent To Module Responsibility

- Route through the relevant agent before loading module docs.
- The active agent chooses which module to inspect based on the task and diff scope.
- Default loading order is:
  1. `agents/<agent>/README.md`
  2. `agents/<agent>/tools.md` and `agents/<agent>/memory.md` when needed
  3. `modules/<module>/README.md`
  4. `modules/<module>/<module>.md`
  5. `references/*` only for evidence-level checks
- Do not load all agents and modules eagerly. Prefer agent-first, task-scoped loading.

## Modules Directory Guidance

- `modules/` is generated based on the target codebase (not fixed).
- Recommended buckets: `frontend`, `backend`, `qa`, `reviewer` (only if inferred).
- Each module may contain multiple detailed docs; keep an overview `modules/<module>/README.md` and a `modules/<module>/<module>.md` for detailed module notes.
- If a domain is present (e.g., `mobile`, `data`, `ops`, `infra`), create that module.

## Generation Rules

### Modules

- Each module folder must include:
  - `modules/<module>/README.md` (overview)
  - `modules/<module>/<module>.md` (details: Scope, Key Responsibilities, Important Notes, Interfaces & Dependencies)
- If a module is large, split into multiple files (e.g., `A.md`, `B.md`, `C.md`). In that case, `<module>.md` becomes an index/summary that describes each sub-file and when to load it.

### Agents

- Create one folder per agent under `agents/<agent>/`.
- Agent list is inferred from module buckets; always include `reviewer`.
- Each agent should act as the routing layer that decides which module docs to load for its task.
- Each agent folder must include:
  - `README.md` with Role, Principles, Responsibilities, Deliverables, Working Style, Notes
  - `tools.md` (Markdown)
  - `memory.md` (Markdown)
  - `decisions.jsonl` (JSONL, one decision per line)
  - `fails.jsonl` (JSONL, one failure per line)
- `README.md` must also include a brief description of the purpose of other files in the current agent directory.
