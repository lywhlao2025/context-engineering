# Output Templates

Use this reference when filling generated L1/L2/L3 context documents.

## L1 (`skill.md`)

- Project summary (what it is + target users)
- Architecture & boundaries
- Agent routing and loading order
- Entrypoints + build/run
- Module navigation
- Progressive loading model (L1/L2/L3)
- Spec-driven development:
  - Spec-first rule (no implementation without a spec)
  - Spec template (scope, interfaces, edge cases/errors, acceptance criteria, tests)
  - Change control (spec updates recorded in decisions)
  - Traceability (code/tests map back to spec items)
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`modules/<module>/README.md`)

- Responsibilities
- Key areas/files with file + line evidence
- Typical tasks
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`modules/<module>/<module>.md`)

- Scope
- Key Responsibilities
- Important Notes (constraints, risks, decisions)
- Interfaces & Dependencies
- Key flows with file + line evidence when applicable
- Testing/QA hooks with file + line evidence when applicable
- If an AUTO block is present, it should act as a generated evidence supplement layer rather than repeating the same top-level section headings verbatim.
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`agents/<agent>/README.md`)

- Role
- Principles
- Responsibilities
- Deliverables
- Working Style
- Notes
- Module-loading responsibility for this agent
- Description of other files in the agent directory
- Generated content must be usable as real sub-agent initialization context, not left as placeholders or TODO-only text.

## L3 (`references/entrypoints.md`)

- Entry file index with file + line evidence
- Core logic/index files
- Data/storage index
- i18n index
- Build/release/ops entrypoints
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.
