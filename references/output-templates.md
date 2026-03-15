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
- Key areas/files with file + symbol evidence (line hint when available)
- Typical tasks
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`modules/<module>/<module>.md`)

- Scope
- Functional Subdomains
- Key Responsibilities
- Important Notes (constraints, risks, decisions)
- Interfaces & Dependencies
- Key flows with file + symbol evidence (line hint when available) when applicable
- Testing/QA hooks with file + symbol evidence (line hint when available) when applicable
- If an AUTO block is present, it should act as a generated evidence supplement layer rather than repeating the same top-level section headings verbatim.
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`modules/<module>/<feature>.md`)

- Feature scope inside the parent technical module
- Responsibilities for that specific business slice
- Entrypoints with file + symbol evidence (line hint when available)
- Testing hooks with file + symbol evidence (line hint when available)
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

- Entry file index with file + symbol evidence (line hint when available)
- Core logic/index files
- Data/storage index
- i18n index
- Build/release/ops entrypoints
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`references/feature-map.md`)

- Shared business features across technical modules
- Links such as `frontend/new-sign.md` and `backend/new-sign.md`
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`references/requirements-map.md`)

- PRD requirement candidates and trace rows (`req_id`, `prd_ref`, `feature_keys`, `modules`)
- Mapped code/test references for each requirement row
- Confidence and status (`mapped`, `partial`, `unresolved`) for delivery gating
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.
