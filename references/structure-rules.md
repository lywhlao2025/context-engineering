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
  5. `modules/<module>/<feature>.md` when stable business slices exist
  6. `references/requirements-map.md` when the task starts from PRD requirements
  7. `references/domain-model.md` when the task needs entity/state/rule planning
  8. `references/*` only for evidence-level checks
- Do not load all agents and modules eagerly. Prefer agent-first, task-scoped loading.

## Modules Directory Guidance

- `modules/` is generated based on the target codebase (not fixed).
- Recommended buckets: `frontend`, `backend`, `qa`, `reviewer` (only if inferred).
- Treat the first layer under `modules/` as technical/runtime boundaries.
- Each module may contain multiple detailed docs; keep an overview `modules/<module>/README.md`, a module index/detail file `modules/<module>/<module>.md`, and when stable business slices exist, additional feature docs such as `modules/<module>/new-sign.md`.
- If a domain is present (e.g., `mobile`, `data`, `ops`, `infra`), create that module.

## Generation Rules

### Modules

- Each module folder must include:
  - `modules/<module>/README.md` (overview)
  - `modules/<module>/<module>.md` (details: Scope, Functional Subdomains, Key Responsibilities, Important Notes, Interfaces & Dependencies)
- If stable business slices exist inside that technical module, generate `modules/<module>/<feature>.md` files for them.
- If a module is large, split into multiple files (e.g., `A.md`, `B.md`, `C.md`). In that case, `<module>.md` becomes an index/summary that describes each sub-file and when to load it.

### Agents

- Create one folder per agent under `agents/<agent>/`.
- Agent list is inferred from module buckets; always include `reviewer`.
- Each agent should act as the routing layer that decides which module docs to load for its task.
- Agent docs are part of the generated context contract; they must be filled with usable initialization content during sync, not left as empty shells.
- Each agent folder must include:
  - `README.md` with Role, Principles, Responsibilities, Deliverables, Working Style, Notes
  - `tools.md` (Markdown)
  - `memory.md` (Markdown)
  - `decisions.jsonl` (JSONL, one decision per line)
  - `fails.jsonl` (JSONL, one failure per line)
- `README.md` must also include a brief description of the purpose of other files in the current agent directory.
- Agent docs should follow a harness-style contract:
  - Explicit scope boundary and non-goals
  - Deterministic task loop (`observe -> plan -> act -> verify -> record`)
  - Clear escalation/stop conditions for ambiguity and risk
  - Verification and feedback-loop hooks tied to concrete commands/evidence
